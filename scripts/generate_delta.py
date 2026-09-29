#!/usr/bin/env python3
"""
AER ST37 Monthly Micro-Delta Patch Generator
Compares previous month's wellpad_wells.db against current month's wellpad_wells.db.
Generates a tiny compressed delta patch (delta_YYYY_MM.json.gz) < 300 KB for mobile sync.
"""

import argparse
import gzip
import json
import os
import sqlite3
import sys
from datetime import datetime


def compare_databases(old_db_path, new_db_path, output_patch_path):
    print(f"[{datetime.now().isoformat()}] Generating monthly delta patch...")
    print(f"  Old DB: {old_db_path}")
    print(f"  New DB: {new_db_path}")
    print(f"  Output: {output_patch_path}")

    if not os.path.exists(old_db_path) or not os.path.exists(new_db_path):
        raise FileNotFoundError("Both old and new databases must exist to compute a delta.")

    conn_old = sqlite3.connect(old_db_path)
    conn_new = sqlite3.connect(new_db_path)

    # Attach old database into new database connection for fast SQL set operations
    cursor = conn_new.cursor()
    cursor.execute(f"ATTACH DATABASE '{os.path.abspath(old_db_path)}' AS old_db;")

    # 1. Detect Inserts (Wells in new DB that were not in old DB)
    print("Computing newly licensed wellbores (INSERTS)...")
    cursor.execute("""
        SELECT uwi, surface_lsd_key, well_name, licensee, licence_no,
               status_mode, status_fluid, is_disposal, is_active
        FROM lease_wells
        WHERE uwi NOT IN (SELECT uwi FROM old_db.lease_wells);
    """)
    columns = [
        "uwi", "surface_lsd_key", "well_name", "licensee", "licence_no",
        "status_mode", "status_fluid", "is_disposal", "is_active"
    ]
    inserts = [dict(zip(columns, row)) for row in cursor.fetchall()]
    print(f"  Found {len(inserts):,} new wells.")

    # 2. Detect Updates (Wells present in both, but status, licensee, or fluid changed)
    print("Computing modified wellbores (UPDATES)...")
    cursor.execute("""
        SELECT n.uwi, n.surface_lsd_key, n.well_name, n.licensee, n.licence_no,
               n.status_mode, n.status_fluid, n.is_disposal, n.is_active
        FROM lease_wells n
        JOIN old_db.lease_wells o ON n.uwi = o.uwi
        WHERE n.status_mode != o.status_mode
           OR n.status_fluid != o.status_fluid
           OR n.is_disposal != o.is_disposal
           OR n.is_active != o.is_active
           OR n.licensee != o.licensee
           OR n.well_name != o.well_name;
    """)
    updates = [dict(zip(columns, row)) for row in cursor.fetchall()]
    print(f"  Found {len(updates):,} updated wells.")

    # 3. Detect Deletes (Rare, but tracks rescinded licences)
    print("Computing removed wellbores (DELETES)...")
    cursor.execute("""
        SELECT uwi FROM old_db.lease_wells
        WHERE uwi NOT IN (SELECT uwi FROM lease_wells);
    """)
    deletes = [row[0] for row in cursor.fetchall()]
    print(f"  Found {len(deletes):,} deleted wells.")

    payload = {
        "version": 1,
        "generated_at": datetime.now().isoformat(),
        "stats": {
            "inserts": len(inserts),
            "updates": len(updates),
            "deletes": len(deletes)
        },
        "inserts": inserts,
        "updates": updates,
        "deletes": deletes
    }

    # Write compressed json.gz
    json_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    raw_kb = len(json_bytes) / 1024

    with gzip.open(output_patch_path, 'wb', compresslevel=9) as f:
        f.write(json_bytes)

    gz_kb = os.path.getsize(output_patch_path) / 1024
    print(f"\nDelta Patch generated: {output_patch_path}")
    print(f"  Uncompressed: {raw_kb:.1f} KB")
    print(f"  Compressed:   {gz_kb:.1f} KB (mobile-ready micro-delta!)")

    conn_new.close()
    conn_old.close()


def main():
    parser = argparse.ArgumentParser(description="Generate AER ST37 Monthly Delta Patch")
    parser.add_argument("--old-db", required=True, help="Path to previous month's wellpad_wells.db")
    parser.add_argument("--new-db", required=True, help="Path to current month's wellpad_wells.db")
    parser.add_argument("--output", required=True, help="Path for output delta .json.gz")
    args = parser.parse_args()

    compare_databases(args.old_db, args.new_db, args.output)


if __name__ == "__main__":
    main()
