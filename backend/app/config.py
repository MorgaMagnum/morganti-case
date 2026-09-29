"""Paths and tunables. Every path can be overridden with an environment variable."""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("CC_CONFIG_DIR", ROOT_DIR / "config"))
DATA_DIR = Path(os.environ.get("CC_DATA_DIR", ROOT_DIR / "data"))
MEDIA_DIR = DATA_DIR / "media"
BROWSER_PROFILE_DIR = DATA_DIR / "browser-profile"
DATABASE_URL = os.environ.get("CC_DATABASE_URL", f"sqlite:///{(DATA_DIR / 'cerca_case.db').as_posix()}")

BOUNDARY_FILE = CONFIG_DIR / "cascina_boundary.geojson"
FRAZIONI_FILE = CONFIG_DIR / "frazioni.json"
AGENCIES_FILE = CONFIG_DIR / "agencies.yaml"

COMUNE_NAME = "Cascina"
COMUNE_CENTER = (43.6760, 10.5520)  # lat, lng

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
GEOCODER_USER_AGENT = "morganti-cerca-case/0.1 (uso personale)"

REQUEST_DELAY_RANGE = (2.0, 4.0)  # seconds between requests to the same site
MAX_PAGES_PER_SEARCH = 60
MISSED_RUNS_BEFORE_INACTIVE = 2
BROWSER_HEADLESS = os.environ.get("CC_BROWSER_HEADLESS", "0") == "1"

# "consultazione": read-only copy fed by CSV imports (no crawling, no browser needed).
APP_MODE = "consultazione" if os.environ.get("CC_MODE", "").lower() == "consultazione" else "completo"
CAN_SCRAPE = APP_MODE == "completo"
MAX_IMPORT_BYTES = 50 * 1024 * 1024


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
