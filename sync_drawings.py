import os
import re
import json
import requests
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import unquote
from xml.etree import ElementTree as ET

WEBDAV_BASE_URL = os.environ.get("NC_URL") or ""
USERNAME = os.environ.get("NC_USER") or ""
APP_PASSWORD = os.environ.get("NC_PASS") or ""

SMTP_USER = os.environ.get("SMTP_USER") or ""
SMTP_PASS = os.environ.get("SMTP_PASS") or ""

VISITED_URLS = set()

def get_webdav_folder_contents(url):
    auth = requests.auth.HTTPBasicAuth(USERNAME, APP_PASSWORD)
    headers = {"Depth": "1", "Content-Type": "application/xml"}
    body = """<?xml version="1.0" encoding="utf-8" ?>
    <d:propfind xmlns:d="DAV:">
        <d:prop>
            <d:resourcetype/>
            <d:getlastmodified/>
        </d:prop>
    </d:propfind>"""

    try:
        response = requests.request("PROPFIND", url, auth=auth, headers=headers, data=body, timeout=15)
        if response.status_code != 207:
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
        print(f"Error accessing {url}: {e}")
        return []

def scan_nextcloud_tree(current_url, current_path_str=""):
    norm_url = current_url.rstrip('/')
    if norm_url in VISITED_URLS:
        return []
    VISITED_URLS.add(norm_url)

    results = []
    items = get_webdav_folder_contents(current_url)
    drawings_in_this_folder = []

    for item in items:
        raw_href = item["href"]
        decoded_name = unquote(raw_href.rstrip('/').split('/')[-1])
        
        if not decoded_name or decoded_name in [".", "..", "remote.php", "dav"]: 
            continue

        if raw_href.startswith('http'):
            full_sub_url = raw_href
        else:
            base_prefix = current_url.rsplit('/remote.php', 1)[0]
            full_sub_url = base_prefix + raw_href if raw_href.startswith('/') else current_url.rstrip('/') + '/' + raw_href

        full_sub_url = full_sub_url.rstrip('/')

        if item["is_collection"]:
            new_path_str = f"{current_path_str}/{decoded_name}" if current_path_str else decoded_name
            results.extend(scan_nextcloud_tree(full_sub_url, new_path_str))
        else:
            filename = decoded_name
            if filename.lower().endswith(('.pdf', '.dwg')):
                # Improved regex to handle rev.00, rev_01, rev02, etc.
                rev_match = re.search(r'REV[\s._-]?([A-Z0-9]+)', filename, re.IGNORECASE)
                if rev_match:
                    rev_tag = f"REV {rev_match.group(1).upper()}"
                else:
                    rev_tag = "REV 00"
                
                mod_date = "Recent"
                if item["last_modified"]:
                    try:
                        mod_date = item["last_modified"][:10]
                    except:
                        pass

                drawings_in_this_folder.append({
                    "filename": filename,
                    "rev": rev_tag,
                    "uploaded": mod_date,
                    "status": "latest",
                    "isNew": False
                })

    if drawings_in_this_folder:
        results.append({
            "path": current_path_str,
            "drawings": drawings_in_this_folder
        })

    return results

def send_email_alerts(new_items):
    if not new_items or not SMTP_USER or not SMTP_PASS:
        return

    try:
        with open("recipients.json", "r") as f:
            recipients = json.load(f).get("recipients", [])
    except Exception:
        recipients = []

    if not recipients:
        return

    subject = f"🚨 ALLCON ALERT: {len(new_items)} New/Updated Drawing(s) Detected"
    body = "The following new drawings or revisions were indexed from Nextcloud:\n\n"
    for item in new_items:
        body += f"• [{item['path']}] {item['filename']} ({item['rev']})\n"
    body += "\nAccess your dashboard to view the full long-term revision history."

    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = ", ".join(recipients)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, recipients, msg.as_string())
        server.quit()
        print("Email notifications dispatched successfully.")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    if not WEBDAV_BASE_URL:
        print("CRITICAL: Missing NC_URL secret variable.")
        exit(1)

    # Load existing state to compare for changes
    existing_drawings_map = {}
    if os.path.exists("drawing-data.json"):
        try:
            with open("drawing-data.json", "r", encoding="utf-8") as f:
                old_data = json.load(f)
                for pkg in old_data:
                    for d in pkg.get("drawings", []):
                        existing_drawings_map[f"{pkg['path']}/{d['filename']}"] = d.get("rev")
        except:
            pass

    start_url = WEBDAV_BASE_URL.rstrip('/') + '/AllconData'
    scanned_data = scan_nextcloud_tree(start_url, "AllconData")

    newly_detected = []
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    for pkg in scanned_data:
        for d in pkg["drawings"]:
            key = f"{pkg['path']}/{d['filename']}"
            if key not in existing_drawings_map or existing_drawings_map[key] != d["rev"]:
                d["isNew"] = True
                newly_detected.append({
                    "timestamp": timestamp_str,
                    "path": pkg["path"],
                    "filename": d["filename"],
                    "rev": d["rev"],
                    "uploaded": d["uploaded"]
                })
            else:
                d["isNew"] = False

    # Save current dashboard snapshot
    with open("drawing-data.json", "w", encoding="utf-8") as f:
        json.dump(scanned_data, f, indent=4, ensure_ascii=False)

    # Load and append to permanent long-term history file
    history_log = []
    if os.path.exists("revision-history.json"):
        try:
            with open("revision-history.json", "r", encoding="utf-8") as f:
                history_log = json.load(f)
        except:
            pass

    if newly_detected:
        for item in newly_detected:
            history_log.insert(0, item)
        
        with open("revision-history.json", "w", encoding="utf-8") as f:
            json.dump(history_log, f, indent=4, ensure_ascii=False)

        print(f"Detected {len(newly_detected)} new or updated drawings. Updating history and sending alerts...")
        send_email_alerts(newly_detected)
    else:
        print("Scan complete. No new revisions found.")
