#!/usr/bin/env python3
"""
AER ST37 Automated Prober & Change-Detection Engine
Sends a lightweight HTTP HEAD request (~600 bytes) to the AER static CDN.
Learns the monthly publication day and triggers ETL processing when a change is detected.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime

AER_URL = "https://static.aer.ca/prd/documents/sts/st37/ST_37_Excel.zip"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "st37_probe_state.json")
HISTORY_FILE = os.path.join(SCRIPT_DIR, "st37_release_history.json")


def probe_remote(url=AER_URL):
    now_str = datetime.now().isoformat()
    print(f"[{now_str}] Probing AER endpoint: {url}")
    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "WellPadBot/1.0 (https://github.com/caddie23/WP)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            headers = resp.headers
            etag = headers.get("ETag")
            md5 = headers.get("Content-MD5")
            last_modified = headers.get("Last-Modified")
            content_length = headers.get("Content-Length")
            return {
                "status": resp.status,
                "etag": etag,
                "md5": md5,
                "last_modified": last_modified,
                "content_length": int(content_length) if content_length else None
            }
    except Exception as e:
        print(f"Error probing AER server: {e}", file=sys.stderr)
        return None


def run_probe():
    info = probe_remote()
    if not info:
        sys.exit(1)

    print(f"Server Response: Status={info['status']}")
    print(f"  Last-Modified:  {info['last_modified']}")
    print(f"  Content-MD5:    {info['md5']}")
    print(f"  ETag:           {info['etag']}")
    print(f"  Content-Length: {info['content_length']} bytes (~{info['content_length'] / (1024*1024):.1f} MB)")

    # Read existing state
    last_state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                last_state = json.load(f)
        except Exception as e:
            print(f"Warning: could not read state file: {e}")

    prev_md5 = last_state.get("md5")
    prev_etag = last_state.get("etag")

    changed = (info["md5"] != prev_md5) or (info["etag"] != prev_etag)

    if changed:
        now_dt = datetime.now()
        now_iso = now_dt.isoformat()
        print("\n>>> NEW FILE DETECTED!")
        print(f"   Previous MD5: {prev_md5} -> New MD5: {info['md5']}")
        print(f"   Previous ETag: {prev_etag} -> New ETag: {info['etag']}")

        # Read history log to learn day-of-month and day-of-week patterns
        history = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception as e:
                print(f"Warning: could not read history file: {e}")

        history.append({
            "detected_at": now_iso,
            "aer_last_modified": info["last_modified"],
            "etag": info["etag"],
            "md5": info["md5"],
            "bytes": info["content_length"],
            "day_of_month": now_dt.day,
            "day_of_week": now_dt.strftime("%A"),
            "hour_utc": now_dt.hour
        })

        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

        # Save new state
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "last_checked": now_iso,
                "etag": info["etag"],
                "md5": info["md5"],
                "last_modified": info["last_modified"],
                "content_length": info["content_length"]
            }, f, indent=2)

        print(f"Saved state to {STATE_FILE} and logged event to {HISTORY_FILE}")
        return True
    else:
        print(f"\n[OK] No change detected since {last_state.get('last_modified')}. Exiting.")
        # Update last checked timestamp
        last_state["last_checked"] = datetime.now().isoformat()
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(last_state, f, indent=2)
        return False


if __name__ == "__main__":
    is_changed = run_probe()
    if is_changed:
        sys.exit(0) # Change detected (can trigger pipeline)
    else:
        sys.exit(2) # No change detected
