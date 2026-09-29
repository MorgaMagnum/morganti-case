"""Read-only copy of Cerca Case: shows the listings imported from a CSV export.

Started by "Apri Cerca Case.bat" in the package made by crea-versione-consultazione.ps1.
Made for someone who is not technical, so on every start it:
- imports the newest "cerca-case-*.csv" found next to the package or in Downloads
  (where WhatsApp and e-mail attachments land), unless it was already imported;
- puts a "Cerca Case" icon on the Desktop the first time;
- opens the browser as soon as the server answers (or at once if already running).
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

os.environ["CC_MODE"] = "consultazione"  # before importing the app: it decides which endpoints exist

PORT = int(os.environ.get("CC_PORT", "8010"))
URL = f"http://127.0.0.1:{PORT}"
READY_TIMEOUT_S = 30
EXPORT_GLOB = "cerca-case*.csv"  # name given by "Esporta CSV", e.g. cerca-case-2026-09-29 (1).csv
PACKAGE_DIR = Path(__file__).resolve().parents[2]  # <package>/programma/backend/consultazione.py
LAUNCHER = PACKAGE_DIR / "Apri Cerca Case.bat"


def _answers() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/api/info", timeout=1) as resp:
            return resp.status == 200
    except OSError:
        return False


def _open_browser() -> None:
    if os.environ.get("CC_NO_BROWSER") != "1":
        webbrowser.open(URL)


def _open_when_ready() -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if _answers():
            _open_browser()
            return
        time.sleep(0.5)


def _candidate_files() -> list[Path]:
    folders = [PACKAGE_DIR, Path.home() / "Downloads", Path.home() / "Desktop"]
    return [f for folder in folders if folder.is_dir() for f in folder.glob(EXPORT_GLOB) if f.is_file()]


def auto_import() -> None:
    """Import the newest export found, once. Importing merges, so a repeat would be harmless anyway."""
    from app import config

    files = _candidate_files()
    if not files:
        return
    newest = max(files, key=lambda f: f.stat().st_mtime)
    stamp = {"file": str(newest), "mtime": newest.stat().st_mtime, "size": newest.stat().st_size}
    marker = config.DATA_DIR / "ultimo-import.json"
    try:
        if json.loads(marker.read_text(encoding="utf-8")) == stamp:
            return
    except (OSError, ValueError):
        pass

    from sqlmodel import Session

    from app.db import engine, init_db
    from pipeline.transfer import ImportFileError, import_csv

    print(f"Carico gli immobili dal file {newest.name}...")
    init_db()
    try:
        with Session(engine) as session:
            result = import_csv(session, newest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ImportFileError) as exc:
        print(f"Non riesco a leggere {newest.name}: {exc}")
        return
    print(f"Fatto: {result.new} nuovi, {result.updated} aggiornati.")
    marker.write_text(json.dumps(stamp), encoding="utf-8")


def ensure_desktop_icon() -> None:
    if os.environ.get("CC_NO_SHORTCUT") == "1" or not LAUNCHER.exists():
        return
    quote = lambda p: str(p).replace("'", "''")  # noqa: E731  (PowerShell single-quoted string)
    script = (
        "$d=[Environment]::GetFolderPath('Desktop'); $p=Join-Path $d 'Cerca Case.lnk';"
        "if(-not (Test-Path $p)){ $l=(New-Object -ComObject WScript.Shell).CreateShortcut($p);"
        f"$l.TargetPath='{quote(LAUNCHER)}'; $l.WorkingDirectory='{quote(PACKAGE_DIR)}';"
        "$l.IconLocation=\"$env:SystemRoot\\System32\\imageres.dll,1\"; $l.Save() }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], timeout=20, check=False,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass  # the icon is a convenience: never block the start for it


def main() -> int:
    if _answers():
        _open_browser()
        return 0
    ensure_desktop_icon()
    auto_import()
    print()
    print("Cerca Case è aperto nel browser.")
    print("Lascia aperta questa finestra finché lo usi. Quando hai finito, chiudila.")
    threading.Thread(target=_open_when_ready, daemon=True).start()

    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
