#!/usr/bin/env python3
"""
Prints the registry version (YYYYMMDD) for the build about to be published.

- New AER month: YYYYMM01 of AER's Last-Modified date (not the date the job ran).
- Same-month re-issue or forced rebuild: previous version + 1 (e.g. 20261001 -> 20261002),
  so every published build gets a distinct, increasing version and apps see it as new.
  The app displays only the year and month, so it still shows as that month.
"""

import argparse
import json
import sys
from email.utils import parsedate_to_datetime


def main():
    parser = argparse.ArgumentParser(description="Compute the next well registry version")
    parser.add_argument("--manifest", default="manifest.json")
    parser.add_argument("--state", default="scripts/st37_probe_state.json")
    args = parser.parse_args()

    with open(args.manifest) as f:
        prev_version = int(json.load(f)["latest_db_version"])

    with open(args.state) as f:
        last_modified = json.load(f).get("last_modified")
    if not last_modified:
        print("No AER Last-Modified date in probe state", file=sys.stderr)
        sys.exit(1)

    aer_date = parsedate_to_datetime(last_modified)
    month_version = int(aer_date.strftime("%Y%m01"))

    if month_version > prev_version:
        new_version = month_version
    else:
        new_version = prev_version + 1
        if new_version // 100 != prev_version // 100 or new_version % 100 > 28:
            print(f"Too many rebuilds in the month of {prev_version}", file=sys.stderr)
            sys.exit(1)

    print(new_version)


if __name__ == "__main__":
    main()
