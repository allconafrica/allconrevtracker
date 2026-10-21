import os
import re
import json
import requests
from urllib.parse import unquote
from xml.etree import ElementTree as ET

WEBDAV_BASE_URL = os.environ.get("NC_URL") or ""
USERNAME = os.environ.get("NC_USER") or ""
APP_PASSWORD = os.environ.get("NC_PASS") or ""

def get_webdav_folder_contents(url):
    auth = requests.auth.HTTPBasicAuth(USERNAME, APP_PASSWORD)
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
            print(f"HTTP {response.status_code} accessing: {url}")
            return []

        tree = ET.fromstring(response.content)
        items = []
        for resp in tree.findall("{DAV:}response"):
            href_elem = resp.find("{DAV:}href")
            if href_elem is None: 
                continue
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
        print(f"Error connecting to {url}: {e}")
        return []

def scan_nextcloud_tree(current_url, current_path_str=""):
    results = []
    items = get_webdav_folder_contents(current_url)

    for item in items:
        raw_href = item["href"]
        decoded_name = unquote(raw_href.rstrip('/').split('/')[-1])
        
        # Skip root level repeated self-references
        if not decoded_name or decoded_name in ["Files", "remote.php", "dav"]: 
            continue

        if raw_href.startswith('http'):
            full_sub_url = raw_href
        else:
            base_prefix = current_url.rsplit('/remote.php', 1)[0]
            full_sub_url = base_prefix + raw_href if raw_href.startswith('/') else current_url.rstrip('/') + '/' + raw_href

        if item["is_collection"]:
            # Clean up path representation
            new_path_str = f"{current_path_str}/{decoded_name}" if current_path_str else decoded_name
            
            name_upper = decoded_name.upper()
            
            # Check if this folder contains drawings (e.g. AFC, PDF, DRAWINGS, REVISION)
            is_drawing_folder = any(keyword in name_upper for keyword in ["AFC", "PDF", "DRAWING", "REV"])
            
            if is_drawing_folder:
                folder_files = get_webdav_folder_contents(full_sub_url)
                drawings = []
                
                for file_item in folder_files:
                    if not file_item["is_collection"]:
                        filename = unquote(file_item["href"].rstrip('/').split('/')[-1])
                        if filename.lower().endswith(('.pdf', '.dwg')):
                            rev_match = re.search(r'(REV\s?\d+|REV[A-Z0-9_-]+)', filename, re.IGNORECASE)
                            rev_tag = rev_match.group(0).upper() if rev_match else "REV 00"
                            
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
                    print(f"==> MATCHED {len(drawings)} files in: {new_path_str}")
                    results.append({
                        "path": new_path_str,
                        "drawings": drawings
                    })
                else:
                    # Keep searching deeper inside this folder if no immediate files were found
                    results.extend(scan_nextcloud_tree(full_sub_url, new_path_str))
            else:
                # Recurse deeper into subdirectories (e.g., AllconData -> Projects -> Clients)
                results.extend(scan_nextcloud_tree(full_sub_url, new_path_str))

    return results

if __name__ == "__main__":
    if not WEBDAV_BASE_URL:
        print("CRITICAL: Missing NC_URL secret variable.")
        exit(1)

    start_url = WEBDAV_BASE_URL.rstrip('/') + '/AllconData'
    print(f"Starting deep crawl at: {start_url}")
    
    scanned_data = scan_nextcloud_tree(start_url, "AllconData")
    print(f"Scan complete. Found {len(scanned_data)} drawing packages.")
    
    with open("drawing-data.json", "w", encoding="utf-8") as f:
        json.dump(scanned_data, f, indent=4, ensure_ascii=False)
