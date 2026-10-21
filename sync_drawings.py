import os
import requests
from urllib.parse import unquote
from xml.etree import ElementTree as ET

WEBDAV_BASE_URL = os.environ.get("NC_URL") or ""
USERNAME = os.environ.get("NC_USER") or ""
APP_PASSWORD = os.environ.get("NC_PASS") or ""

def list_webdav(url):
    auth = requests.auth.HTTPBasicAuth(USERNAME, APP_PASSWORD)
    headers = {"Depth": "1", "Content-Type": "application/xml"}
    body = """<?xml version="1.0" encoding="utf-8" ?>
    <d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>"""
    try:
        res = requests.request("PROPFIND", url, auth=auth, headers=headers, data=body)
        print(f"\n--- Checking: {url} (Status: {res.status_code}) ---")
        if res.status_code != 207:
            return
        
        tree = ET.fromstring(res.content)
        for resp in tree.findall("{DAV:}response"):
            href = resp.find("{DAV:}href").text
            name = unquote(href.rstrip('/').split('/')[-1])
            if name:
                print(f"  [Folder/File Found]: {name}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Test base WebDAV URL
    list_webdav(WEBDAV_BASE_URL)
