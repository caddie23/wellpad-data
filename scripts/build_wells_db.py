#!/usr/bin/env python3
"""
AER ST37 Well Registry Database Builder (ETL)
Builds a compact SQLite database (wellpad_wells.db) mapping Surface LSDs to on-lease wellbores and UWIs.

Sourced from Alberta Energy Regulator (AER) ST37:
- ST37_SH.xlsx (Surface Holes)
- ST37_BH.xlsx (Bottom Holes / Wellbores)
- ST37_ Production_Strings.xlsx (Fluid, Mode, Disposal scheme)

Remote URL: https://static.aer.ca/prd/documents/sts/st37/ST_37_Excel.zip
"""

import argparse
import gzip
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime

import pandas as pd

AER_URL = "https://static.aer.ca/prd/documents/sts/st37/ST_37_Excel.zip"
DEFAULT_LOCAL_DIR = r"D:\WellData\ST_37_Excel"
DEFAULT_OUTPUT_DB = r"D:\WellData\wellpad_wells.db"


def parse_lsd_to_key(label):
    if not isinstance(label, str):
        return None
    # Matches patterns like:
    # 04-12-066-03W4, 04-12-066-03 W4, 4-12-66-3W4, 04-12-066-03-W4
    m = re.match(
        r"^(\d{1,2})[- ](\d{1,2})[- ](\d{1,3})[- ](\d{1,2})\s*[-]?W?(\d)$",
        label.strip(),
        re.IGNORECASE,
    )
    if m:
        lsd, sec, twp, rge, mer = map(int, m.groups())
        if 1 <= lsd <= 16 and 1 <= sec <= 36 and 1 <= twp <= 126 and 1 <= rge <= 34 and 4 <= mer <= 6:
            return (((((mer * 100) + rge) * 1000 + twp) * 100 + sec) * 100 + lsd)
    return None


def download_st37_zip(url=AER_URL, dest_dir=None):
    if not dest_dir:
        dest_dir = tempfile.mkdtemp(prefix="aer_st37_")
    zip_path = os.path.join(dest_dir, "ST_37_Excel.zip")
    print(f"[{datetime.now().isoformat()}] Downloading ST37 from {url}...")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "WellPadBot/1.0 (https://github.com/caddie23/WP)"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp, open(zip_path, "wb") as f:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        block_size = 1024 * 1024
        while True:
            chunk = resp.read(block_size)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                percent = (downloaded / total) * 100
                print(f"\r  Downloaded: {downloaded / (1024*1024):.1f} MB / {total / (1024*1024):.1f} MB ({percent:.1f}%)", end="")
    print(f"\nExtracting {zip_path}...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)
    print(f"Extracted to {dest_dir}")
    return dest_dir


def build_database(source_dir, output_db, limit=None, do_gzip=True):
    start_time = datetime.now()
    print(f"[{start_time.isoformat()}] Starting AER ST37 database build...")
    print(f"Source Directory: {source_dir}")
    print(f"Output Database:  {output_db}")

    sh_path = os.path.join(source_dir, "ST37_SH.xlsx")
    bh_path = os.path.join(source_dir, "ST37_BH.xlsx")
    ps_path = os.path.join(source_dir, "ST37_ Production_Strings.xlsx")

    for p in [sh_path, bh_path, ps_path]:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Missing required ST37 file: {p}")

    # 1. Process Surface Holes
    print("\n[Step 1/4] Reading Surface Holes (ST37_SH.xlsx)...")
    df_sh = pd.read_excel(
        sh_path,
        usecols=["Well_Licence_Number", "Licensee", "Licence_Status", "Licence_Surface_Location_Label"],
        nrows=limit
    )
    print(f"  Loaded {len(df_sh):,} surface hole rows.")

    licence_map = {}
    parsed_count = 0
    for _, row in df_sh.iterrows():
        lic_no = row["Well_Licence_Number"]
        label = row["Licence_Surface_Location_Label"]
        key = parse_lsd_to_key(label)
        if key:
            parsed_count += 1
            licence_map[lic_no] = {
                "surface_key": key,
                "licensee": str(row["Licensee"]).strip() if pd.notna(row["Licensee"]) else "",
                "status": str(row["Licence_Status"]).strip() if pd.notna(row["Licence_Status"]) else ""
            }
    print(f"  Parsed {parsed_count:,} valid surface LSD coordinates ({parsed_count / len(df_sh) * 100:.1f}%).")

    # 2. Process Production Strings
    print("\n[Step 2/4] Reading Production Strings (ST37_ Production_Strings.xlsx)...")
    df_ps = pd.read_excel(
        ps_path,
        usecols=["Well_UWI", "Status_Fluid", "Status_Mode", "Scheme_Type", "Scheme_Sub_Type"],
        nrows=limit
    )
    print(f"  Loaded {len(df_ps):,} production string rows.")

    ps_map = {}
    for _, row in df_ps.iterrows():
        uwi = str(row["Well_UWI"]).strip()
        fluid = str(row["Status_Fluid"]).strip() if pd.notna(row["Status_Fluid"]) else None
        mode = str(row["Status_Mode"]).strip() if pd.notna(row["Status_Mode"]) else None
        scheme = str(row["Scheme_Type"]).strip() if pd.notna(row["Scheme_Type"]) else ""
        sub_scheme = str(row["Scheme_Sub_Type"]).strip() if pd.notna(row["Scheme_Sub_Type"]) else ""

        is_disposal = (
            "DISPOSAL" in scheme.upper()
            or "DISPOSAL" in sub_scheme.upper()
            or (mode and "DISPOSAL" in mode.upper())
        )

        # Prioritize active/disposal if multiple strings exist for the same UWI
        if uwi in ps_map:
            prev = ps_map[uwi]
            ps_map[uwi] = {
                "fluid": fluid or prev["fluid"],
                "mode": mode or prev["mode"],
                "is_disposal": 1 if (is_disposal or prev["is_disposal"] == 1) else 0
            }
        else:
            ps_map[uwi] = {
                "fluid": fluid,
                "mode": mode,
                "is_disposal": 1 if is_disposal else 0
            }
    print(f"  Aggregated {len(ps_map):,} unique well string states.")

    # 3. Process Bottom Holes & Build Final Records
    print("\n[Step 3/4] Reading Bottom Holes (ST37_BH.xlsx) & Joining...")
    df_bh = pd.read_excel(
        bh_path,
        usecols=["Well_UWI", "Well_Licence_Number", "Well_Name", "Licensee", "Licence_Status"],
        nrows=limit
    )
    print(f"  Loaded {len(df_bh):,} bottom hole rows.")

    # Set up SQLite database
    if os.path.exists(output_db):
        os.remove(output_db)

    conn = sqlite3.connect(output_db)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = OFF;")
    cursor.execute("PRAGMA synchronous = 0;")

    cursor.execute("""
        CREATE TABLE lease_wells (
            uwi TEXT PRIMARY KEY,
            surface_lsd_key INTEGER NOT NULL,
            well_name TEXT NOT NULL,
            licensee TEXT NOT NULL,
            licence_no TEXT,
            status_mode TEXT,
            status_fluid TEXT,
            is_disposal INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        );
    """)

    insert_sql = """
        INSERT OR REPLACE INTO lease_wells (
            uwi, surface_lsd_key, well_name, licensee, licence_no,
            status_mode, status_fluid, is_disposal, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
    """

    records_to_insert = []
    matched_surface_count = 0

    for _, row in df_bh.iterrows():
        uwi = str(row["Well_UWI"]).strip()
        lic_no = row["Well_Licence_Number"]
        well_name = str(row["Well_Name"]).strip() if pd.notna(row["Well_Name"]) else ""
        licensee = str(row["Licensee"]).strip() if pd.notna(row["Licensee"]) else ""
        lic_status = str(row["Licence_Status"]).strip() if pd.notna(row["Licence_Status"]) else ""

        # Find surface hole
        sh_info = licence_map.get(lic_no)
        if not sh_info:
            continue

        surface_key = sh_info["surface_key"]
        matched_surface_count += 1

        if not licensee:
            licensee = sh_info["licensee"]

        # String details
        ps_info = ps_map.get(uwi, {})
        fluid = ps_info.get("fluid")
        mode = ps_info.get("mode")
        is_disposal = ps_info.get("is_disposal", 0)

        # Status active check
        status_upper = (lic_status or sh_info.get("status", "")).upper()
        mode_upper = (mode or "").upper()
        is_active = 0 if ("ABANDONED" in status_upper or "ABANDONED" in mode_upper or "REC CERT" in status_upper) else 1

        records_to_insert.append((
            uwi,
            surface_key,
            well_name,
            licensee,
            str(lic_no),
            mode,
            fluid,
            is_disposal,
            is_active
        ))

        if len(records_to_insert) >= 50000:
            cursor.executemany(insert_sql, records_to_insert)
            conn.commit()
            records_to_insert.clear()

    if records_to_insert:
        cursor.executemany(insert_sql, records_to_insert)
        conn.commit()
        records_to_insert.clear()

    print(f"  Successfully inserted {matched_surface_count:,} well records.")

    # 4. Create Index & Optimize
    print("\n[Step 4/4] Creating indexes and optimizing SQLite database...")
    cursor.execute("CREATE INDEX idx_wells_surface_key ON lease_wells(surface_lsd_key);")
    conn.commit()
    cursor.execute("VACUUM;")
    conn.close()

    raw_size_mb = os.path.getsize(output_db) / (1024 * 1024)
    print(f"Database built: {output_db} ({raw_size_mb:.2f} MB)")

    if do_gzip:
        gzip_path = output_db + ".gzip"
        print(f"Compressing to {gzip_path}...")
        with open(output_db, "rb") as f_in, gzip.open(gzip_path, "wb", compresslevel=9) as f_out:
            shutil.copyfileobj(f_in, f_out)
        gzip_size_mb = os.path.getsize(gzip_path) / (1024 * 1024)
        print(f"Compressed archive: {gzip_path} ({gzip_size_mb:.2f} MB)")

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n[DONE] Build completed in {elapsed:.1f}s.")


def main():
    parser = argparse.ArgumentParser(description="Build WellPad AER ST37 Well Database")
    parser.add_argument("--remote", action="store_true", help="Download latest ST_37_Excel.zip from AER")
    parser.add_argument("--source-dir", default=DEFAULT_LOCAL_DIR, help="Directory containing uncompressed ST37 Excel files")
    parser.add_argument("--output-db", default=DEFAULT_OUTPUT_DB, help="Path for output SQLite database")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows for fast testing")
    parser.add_argument("--no-gzip", action="store_true", help="Skip gzip compression")
    args = parser.parse_args()

    source_dir = args.source_dir
    temp_dir = None

    if args.remote or not os.path.exists(source_dir):
        print("Using remote AER source...")
        temp_dir = tempfile.mkdtemp(prefix="aer_st37_")
        source_dir = download_st37_zip(dest_dir=temp_dir)

    try:
        build_database(
            source_dir=source_dir,
            output_db=args.output_db,
            limit=args.limit,
            do_gzip=not args.no_gzip
        )
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
