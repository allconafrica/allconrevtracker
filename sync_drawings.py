import os
import re
import json
import requests
from datetime import datetime
from requests.auth import HTTPBasicAuth
from urllib.parse import unquote
from xml.etree import ElementTree as ET

# Pull credentials safely from GitHub Secrets environment variables
WEBDAV_BASE_URL = os.environ.get("NC_URL")
USERNAME = os.environ.get("NC_USER")
APP_PASSWORD = os.environ.get("NC_PASS")
START_PATH = "AllconData/Projects/Clients/"

def get_webdav_folder_contents(url):
    """Performs a PROPFIND request to fetch subfolders and files from Nextcloud."""
    auth = HTTPBasicAuth(USERNAME, APP_PASSWORD)
    headers = {
        "Depth": "1",
        "Content-Type": "application/xml"
    }
    body = """<?xml version="1.0" encoding="utf-8" ?>
    <d:propfind xmlns:d="DAV:">
        <d:prop>
            <d:resourcetype/>
            <d:getlastmodified/>
        </d:prop>
    </d:propfind>"""

    try:
        response = requests.request("PROPFIND", url, auth=auth, headers=headers, data=body)
        if response.status_code != 207:
            print(f"Warning: HTTP {response.status_code} when accessing {url}")
            return []

        tree = ET.fromstring(response.content)
        items = []
        for resp in tree.findall("{DAV:}response"):
            href_elem = resp.find("{DAV:}href")
            if href_elem is None: continue
            href = href_elem.text
            
            propstat = resp.find("{DAV:}propstat")
            prop = propstat.find("{DAV:}prop") if propstat is not None else None
            resourcetype = prop.find("{DAV:}resourcetype") if prop is not None else None
            is_collection = resourcetype is not None and resourcetype.find("{DAV:}collection") is not None
            
            last_mod = ""
            get_last_mod = prop.find("{DAV:}getlastmodified") if prop is not None else None
            if get_last_mod is not None and get_last_mod.text:
                last_mod = get_last_mod.text

            items.append({
                "href": href,
                "is_collection": is_collection,
                "last_modified": last_mod
            })
        return items
    except Exception as e:
        print(f"Connection error on {url}: {e}")
        return []

def scan_nextcloud_tree(current_url, current_path_str=""):
    """Recursively crawls Nextcloud directories looking for AFC drawing folders."""
    results = []
    items = get_webdav_folder_contents(current_url)

    for item in items:
        raw_href = item["href"]
        decoded_name = unquote(raw_href.rstrip('/').split('/')[-1])
        
        if not decoded_name or decoded_name in ["Files", "Clients", "Projects", "AllconData"]: 
            continue

        # Construct full sub-URL correctly based on WebDAV href response
        if raw_href.startswith('http'):
            full_sub_url = raw_href
        else:
            base_prefix = current_url.rsplit('/remote.php', 1)[0]
            full_sub_url = base_prefix + raw_href if raw_href.startswith('/') else current_url.rstrip('/') + '/' + raw_href

        # EXCLUSION RULE: Skip Enquiry, RFQ, or Tender branches automatically
        if any(exclude in decoded_name for exclude in ["1. Enquiry", "RFQ", "Tender"]):
            continue

        if item["is_collection"]:
            # TARGET RULE: When we hit AFC Drawings or PDF subfolders, extract the actual drawing files
            if "2. AFC Drawings" in decoded_name or "2. PDF" in decoded_name:
                pdf_files = get_webdav_folder_contents(full_sub_url)
                drawings = []
                
                for file_item in pdf_files:
                    if not file_item["is_collection"]:
                        filename = unquote(file_item["href"].rstrip('/').split('/')[-1])
                        if filename.lower().endswith(('.pdf', '.dwg')):
                            # Extract real revision tag (e.g. REV 01, REV 02) via Regex
                            rev_match = re.search(r'(REV\s?\d+|REV[A-Z0-9_-]+)', filename, re.IGNORECASE)
                            rev_tag = rev_match.group(0).upper() if rev_match else "REV 00"
                            
                            # Format modification timestamp safely
                            mod_date = "Recent"
                            if file_item["last_modified"]:
                                try:
                                    mod_date = file_item["last_modified"][:10]
                                except:
                                    pass

                            drawings.append({
                                "filename": filename,
                                "rev": rev_tag,
                                "uploaded": mod_date,
                                "status": "latest",
                                "isNew": False
                            })

                if drawings:
                    results.append({
                        "path": current_path_str + "/" + decoded_name,
                        "drawings": drawings
                    })
            else:
                # Recurse deeper into standard subfolders
                results.extend(scan_nextcloud_tree(full_sub_url, current_path_str + "/" + decoded_name))

    return results

if __name__ == "__main__":
    target_url = WEBDAV_BASE_URL.rstrip('/') + '/' + START_PATH.strip('/')
    print(f"Scanning real Nextcloud environment starting at: {START_PATH}...")
    
    scanned_data = scan_nextcloud_tree(target_url, "AllconData/Projects/Clients")
    
    with open("drawing-data.json", "w", encoding="utf-8") as f:
        json.dump(scanned_data, f, indent=4, ensure_ascii=False)
    
    print(f"Sync complete! Generated drawing-data.json with {len(scanned_data)} validated packages.")
