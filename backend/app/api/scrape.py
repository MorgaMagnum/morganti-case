"""Start a crawl from the UI (as a separate process) and report its progress."""

import subprocess
import sys
import threading
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from app import config
from app.db import get_session
from app.models import ScrapeRun, utcnow
from app.schemas import Envelope, RunInfo, ScrapeStatus
from scrapers.registry import SOURCE_LABELS

router = APIRouter(prefix="/api/scrape", tags=["scrape"])
SessionDep = Annotated[Session, Depends(get_session)]

BACKEND_DIR = Path(__file__).resolve().parents[2]
STALE_RUN_AFTER = timedelta(hours=3)

_lock = threading.Lock()
_process: subprocess.Popen | None = None


def _process_running() -> bool:
    return _process is not None and _process.poll() is None


def _db_running(session: Session) -> bool:
    """A crawl started from the command line also counts as running."""
    since = utcnow() - STALE_RUN_AFTER
    count = session.exec(
        select(func.count()).where(ScrapeRun.status == "running", ScrapeRun.started_at >= since)
    ).one()
    return count > 0


def _latest_runs(session: Session) -> list[RunInfo]:
    latest_ids = select(func.max(ScrapeRun.id)).group_by(ScrapeRun.source, ScrapeRun.contract)
    runs = session.exec(select(ScrapeRun).where(ScrapeRun.id.in_(latest_ids)).order_by(ScrapeRun.id)).all()
    return [RunInfo(label=SOURCE_LABELS.get(r.source, r.source), **r.model_dump(exclude={"id"})) for r in runs]


@router.get("/status", response_model=Envelope[ScrapeStatus])
def status(session: SessionDep):
    running = _process_running() or _db_running(session)
    return Envelope(data=ScrapeStatus(running=running, runs=_latest_runs(session)))


@router.post("", response_model=Envelope[ScrapeStatus])
def start(session: SessionDep):
    global _process
    with _lock:
        if _process_running() or _db_running(session):
            return Envelope(success=False, error="Un aggiornamento è già in corso",
                            data=ScrapeStatus(running=True, runs=_latest_runs(session)))
        config.ensure_dirs()
        log = open(config.DATA_DIR / "scrape.log", "ab")
        _process = subprocess.Popen(
            [sys.executable, "cli.py", "scrape"],
            cwd=BACKEND_DIR,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        log.close()  # the child keeps its own handle
    return Envelope(data=ScrapeStatus(running=True, runs=_latest_runs(session)))
