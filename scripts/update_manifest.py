#!/usr/bin/env python3
"""
Rewrites manifest.json for a new well registry release.

The WellPad app catches up from any older version by walking the "deltas" chain
(from -> to), verifying each file's sha256. If the chain has a gap it downloads
"full_db" instead. The legacy single-delta fields are kept for older app builds.
"""

import argparse
import hashlib
import json
import os

RAW_BASE = "https://raw.githubusercontent.com/caddie23/wellpad-data/main"
RELEASE_BASE = "https://github.com/caddie23/wellpad-data/releases/download"


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Update the WellPad well registry manifest")
    parser.add_argument("--manifest", default="manifest.json")
    parser.add_argument("--new-version", type=int, required=True)
    parser.add_argument("--release-date", required=True)
    parser.add_argument("--total-wells", type=int, required=True)
    parser.add_argument("--full-db", required=True, help="Path to the gzipped full database uploaded to the release")
    parser.add_argument("--delta", help="Path (relative to repo root) of the new delta, if one was generated")
    parser.add_argument("--delta-from", type=int, help="Version the new delta applies to")
    parser.add_argument("--keep-deltas", type=int, default=24, help="How many monthly deltas to list")
    args = parser.parse_args()

    old = {}
    if os.path.exists(args.manifest):
        with open(args.manifest) as f:
            old = json.load(f)

    deltas = [d for d in old.get("deltas", []) if d.get("to", 0) <= args.new_version]

    if args.delta and args.delta_from and args.delta_from < args.new_version:
        # Replace any earlier entry for the same step (e.g. a forced rebuild)
        deltas = [d for d in deltas if not (d["from"] == args.delta_from and d["to"] == args.new_version)]
        deltas.append({
            "from": args.delta_from,
            "to": args.new_version,
            "url": f"{RAW_BASE}/{args.delta}",
            "sha256": sha256_of(args.delta),
            "size_bytes": os.path.getsize(args.delta),
        })

    deltas.sort(key=lambda d: d["to"])
    deltas = deltas[-args.keep_deltas:]

    manifest = {
        "schema_version": 2,
        "latest_db_version": args.new_version,
        "release_date": args.release_date,
        "total_wells": args.total_wells,
        "deltas": deltas,
        "full_db": {
            "version": args.new_version,
            "url": f"{RELEASE_BASE}/v{args.new_version}/wellpad_wells.db.gzip",
            "sha256": sha256_of(args.full_db),
            "size_bytes": os.path.getsize(args.full_db),
        },
    }

    # Legacy single-delta fields (app builds before schema 2 read only these)
    last = deltas[-1] if deltas and deltas[-1]["to"] == args.new_version else None
    if last:
        manifest.update({
            "delta_url": f"{RAW_BASE}/delta_latest.json.gz",
            "delta_from_version": last["from"],
            "delta_sha256": last["sha256"],
            "delta_size_bytes": last["size_bytes"],
        })
    else:
        for key in ("delta_url", "delta_from_version", "delta_sha256", "delta_size_bytes"):
            if key in old:
                manifest[key] = old[key]

    with open(args.manifest, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
