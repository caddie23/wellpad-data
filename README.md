# WellPad AER ST37 Well Registry Data CDN

This public repository hosts automated monthly updates of the Alberta Energy Regulator (AER) ST37 Wellbore & UWI Registry for the **WellPad** Android application.

## Endpoints

- **Manifest:** [`manifest.json`](https://raw.githubusercontent.com/caddie23/wellpad-data/main/manifest.json)
- **Delta Updates:** [`delta_latest.json.gz`](https://raw.githubusercontent.com/caddie23/wellpad-data/main/delta_latest.json.gz)

## Automated Architecture

1. **Daily Probe:** A GitHub Actions runner checks the official AER static CDN daily at 7:15 AM Mountain Time using lightweight HTTP HEAD requests (~600 bytes).
2. **Change Detection:** When the AER publishes its monthly release (typically mid-month), the workflow automatically parses the new Excel workbook containing all active and abandoned well licenses.
3. **Micro-Delta Compilation:** The engine compares the new database against the previous monthly baseline and outputs a compact gzip delta (~150–250 KB) containing new well licenses, re-entries, and status modifications.
4. **Instant Distribution:** The manifest and delta are published here, allowing offline WellPad mobile clients to sync in seconds with minimal bandwidth.
