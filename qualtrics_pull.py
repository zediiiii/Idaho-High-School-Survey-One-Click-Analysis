"""
Idaho High School Math Survey — pull the latest responses from Qualtrics
=======================================================================
Downloads a fresh CSV export of the survey (with the embedded-data School
column) straight from the Qualtrics API, so nobody has to click through
Data & Analysis → Export.

One-time setup (stores your Qualtrics API token in Windows Credential Manager;
the token is typed at a hidden prompt and never printed or saved to a file):

    python qualtrics_pull.py --set-token

Then, whenever you want new data:

    python qualtrics_pull.py                    # every response so far
    python qualtrics_pull.py --year 2026-27     # one school year (1 July – 30 June)

The raw export is research data: per the approved IRB it is stored only in the
research team's secure LC State OneDrive, never in this (public) repository.
The CSV is saved to --out-dir (default: the IRB 2026\\Survey Data folder in
LC State OneDrive). Location and IP columns are removed before saving.
Then run the chart generator on it:

    python survey_viz.py "<saved file>" --school <code> --year 2026-27
"""

import argparse
import csv
import datetime as dt
import getpass
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SURVEY_ID   = "SV_bJwEnVRixF1XbBs"          # Idaho HS Mathematics Student Survey
API_BASE    = "https://co1.qualtrics.com/API/v3"
TOKEN_ENV   = "QUALTRICS_API_TOKEN"
CRED_TARGET = "Qualtrics API token (Idaho HS Math Survey)"
DEFAULT_OUT = os.path.join(os.path.expanduser("~"), "OneDrive - Lewis-Clark State College",
                           "Documents", "IRB 2026", "Survey Data")
SCHOOL_COL  = "School"
DATE_COL    = "RecordedDate"
# Columns that could locate or identify a student; dropped from every saved file.
DROP_COLS   = ["IPAddress", "LocationLatitude", "LocationLongitude",
               "RecipientLastName", "RecipientFirstName", "RecipientEmail", "ExternalReference"]


# ---------------------------------------------------------------------------
# Token storage (Windows Credential Manager, or an environment variable)
# ---------------------------------------------------------------------------

def _cred_api():
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR)]
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    adv.CredFree.argtypes = [ctypes.c_void_p]
    return ctypes, CREDENTIAL, adv


def save_token(token: str):
    if os.name != "nt":
        sys.exit(f"  Credential Manager is Windows-only. Set the {TOKEN_ENV} environment variable instead.")
    ctypes, CREDENTIAL, adv = _cred_api()
    blob = token.encode("utf-16-le")
    cred = CREDENTIAL(Type=1, TargetName=CRED_TARGET, Persist=2,      # generic, local machine
                      CredentialBlobSize=len(blob),
                      CredentialBlob=ctypes.cast(ctypes.create_string_buffer(blob, len(blob)),
                                                 ctypes.POINTER(ctypes.c_char)),
                      UserName="qualtrics")
    if not adv.CredWriteW(ctypes.byref(cred), 0):
        sys.exit(f"  Could not save the token (Windows error {ctypes.get_last_error()}).")


def load_token() -> str | None:
    if os.environ.get(TOKEN_ENV):
        return os.environ[TOKEN_ENV].strip()
    if os.name != "nt":
        return None
    ctypes, CREDENTIAL, adv = _cred_api()
    p = ctypes.POINTER(CREDENTIAL)()
    if not adv.CredReadW(CRED_TARGET, 1, 0, ctypes.byref(p)):
        return None
    try:
        c = p.contents
        return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-16-le")
    finally:
        adv.CredFree(p)


# ---------------------------------------------------------------------------
# Qualtrics export API (v3: start export → poll → download zip)
# ---------------------------------------------------------------------------

def _call(method: str, url: str, token: str, body: dict | None = None) -> bytes:
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-API-TOKEN": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        sys.exit(f"  Qualtrics answered {e.code} {e.reason}: {detail}\n"
                 "  (401/403: check the token with --set-token, and that it belongs to an "
                 "account that can see this survey.)")


def export_csv(token: str, survey_id: str, base: str, start: str | None, end: str | None) -> bytes:
    """Run one response export and return the CSV bytes (labels, not numeric codes)."""
    body = {"format": "csv", "useLabels": True}
    if start:
        body["startDate"] = start
    if end:
        body["endDate"] = end
    root = f"{base}/surveys/{survey_id}/export-responses"
    progress = json.loads(_call("POST", root, token, body))["result"]["progressId"]
    for _ in range(300):                                # up to ~10 minutes
        res = json.loads(_call("GET", f"{root}/{progress}", token))["result"]
        if res["status"] == "complete":
            break
        if res["status"] == "failed":
            sys.exit("  Qualtrics reported that the export failed. Try again in a few minutes.")
        print(f"\r  Exporting … {res.get('percentComplete', 0):.0f}%", end="", flush=True)
        time.sleep(2)
    else:
        sys.exit("  The export did not finish in time. Try again later.")
    print("\r  Exporting … done      ")
    data = _call("GET", f"{root}/{res['fileId']}/file", token)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        return z.read(name)


# ---------------------------------------------------------------------------
# Cleaning and summary
# ---------------------------------------------------------------------------

def strip_identifying(rows: list[list[str]]) -> tuple[list[list[str]], dict]:
    """Drop DROP_COLS from a 3-header-row Qualtrics CSV. Returns (rows, {col: non-blank count})."""
    header = rows[0]
    drop = [i for i, c in enumerate(header) if c in DROP_COLS]
    filled = {header[i]: sum(1 for r in rows[3:] if i < len(r) and r[i].strip()) for i in drop}
    keep = [i for i in range(len(header)) if i not in drop]
    return [[r[i] if i < len(r) else "" for i in keep] for r in rows], filled


def school_year(stamp: str) -> str:
    try:
        d = dt.datetime.fromisoformat(stamp.strip().replace("Z", ""))
    except ValueError:
        return "(no date)"
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def year_bounds(year: str) -> tuple[str, str]:
    start = int(year[:4])
    return f"{start}-07-01T00:00:00Z", f"{start + 1}-07-01T00:00:00Z"


def summarise(rows: list[list[str]]):
    header, data = rows[0], rows[3:]
    print(f"  Responses: {len(data)}")
    if DATE_COL in header:
        i = header.index(DATE_COL)
        for y, n in sorted(Counter(school_year(r[i]) for r in data).items()):
            print(f"    school year {y}: {n}")
    if SCHOOL_COL not in header:
        print("\n  ⚠  No 'School' column in the export. In Qualtrics, open Survey Flow and add an\n"
              "     Embedded Data element named School at the top (value set from URL), so each\n"
              "     school's ?School= code is saved with its responses.")
        return
    i = header.index(SCHOOL_COL)
    print("  By school code:")
    for code, n in sorted(Counter(r[i].strip() or "(no code)" for r in data).items()):
        print(f"    {code:<16} {n}")


def main():
    ap = argparse.ArgumentParser(description="Download the Idaho HS Math Survey responses from Qualtrics.")
    ap.add_argument("--set-token", action="store_true", help="store your Qualtrics API token (hidden prompt)")
    ap.add_argument("--year", help="only one school year, e.g. 2026-27")
    ap.add_argument("--out-dir", default=DEFAULT_OUT, help="where to save the CSV (LC State OneDrive)")
    ap.add_argument("--survey-id", default=SURVEY_ID)
    ap.add_argument("--base", default=API_BASE, help="Qualtrics API base URL (data center)")
    args = ap.parse_args()

    if args.set_token:
        token = getpass.getpass("  Paste your Qualtrics API token (Account Settings → Qualtrics IDs), then Enter: ")
        if not token.strip():
            sys.exit("  No token entered; nothing saved.")
        save_token(token.strip())
        print("  Token saved to Windows Credential Manager.")
        return

    token = load_token()
    if not token:
        sys.exit("  No Qualtrics API token yet. Run:  python qualtrics_pull.py --set-token")

    out_dir = os.path.abspath(args.out_dir)
    if os.path.commonpath([out_dir, SCRIPT_DIR]) == SCRIPT_DIR:
        sys.exit("  Refusing to save raw survey data inside this repository folder (it is public).\n"
                 "  Choose an LC State OneDrive folder with --out-dir.")
    if not os.path.isdir(os.path.dirname(out_dir)):
        sys.exit(f"  Folder not found: {os.path.dirname(out_dir)}  (is LC State OneDrive syncing?)")
    os.makedirs(out_dir, exist_ok=True)

    start = end = None
    if args.year:
        start, end = year_bounds(args.year)
    raw = export_csv(token, args.survey_id, args.base.rstrip("/"), start, end)
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    rows, filled = strip_identifying(rows)
    for col, n in filled.items():
        if n:
            print(f"  ⚠  {col} had values in {n} response(s); removed. Turn on 'Anonymize responses'"
                  " in the survey options so Qualtrics never records it.")

    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    name = f"HS_Math_Survey_{args.year or 'all-years'}_{stamp}.csv"
    path = os.path.join(out_dir, name)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)
    print(f"  Saved: {path}")
    summarise(rows)
    print(f'\n  Next:  python survey_viz.py "{path}"')


if __name__ == "__main__":
    main()
