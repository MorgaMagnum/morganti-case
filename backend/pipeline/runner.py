"""Crawl every configured site and store the results."""

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

from sqlmodel import Session, select

from app import config
from app.db import engine, init_db
from app.models import ScrapeRun, utcnow
from pipeline.geo import CascinaGeo
from pipeline.geocode import NominatimGeocoder
from pipeline.images import ImageClient
from pipeline.store import ListingStore
from scrapers.base import CONTRACTS, Contract, Scraper, ScraperError
from scrapers.fetchers import BrowserFetcher, Fetcher, FetchError, HttpFetcher

log = logging.getLogger(__name__)


@dataclass
class Fetchers:
    http: Fetcher = field(default_factory=HttpFetcher)
    browser: Fetcher = field(default_factory=BrowserFetcher)

    def for_scraper(self, scraper: Scraper) -> Fetcher:
        return self.http if scraper.fetch_mode == "http" else self.browser

    def close(self) -> None:
        for fetcher in (self.http, self.browser):
            try:
                fetcher.close()
            except Exception:  # closing must never mask the real outcome
                log.exception("error closing fetcher")


def crawl_one(
    scraper: Scraper,
    contract: Contract,
    fetcher: Fetcher,
    store: ListingStore,
    session: Session,
    max_pages: int,
) -> ScrapeRun:
    run = ScrapeRun(source=scraper.name, contract=contract)
    session.add(run)
    session.commit()
    counts: Counter = Counter()
    seen: set[str] = set()
    complete = False
    try:
        page, total = 1, 1
        stopped_early = False
        while page <= min(total, max_pages):
            url = scraper.page_url(contract, page)
            log.info("[%s/%s] page %d/%d %s", scraper.name, contract, page, total, url)
            parsed = scraper.parse(fetcher.get(url), contract)
            total = parsed.total_pages
            run.pages = page
            page_ids = {r.external_id for r in parsed.listings}
            if not page_ids or page_ids <= seen:
                # Empty page, or the site ignored our page parameter and served a page we already have.
                log.warning("[%s/%s] page %d is %s, stopping", scraper.name, contract, page,
                            "empty" if not page_ids else "a repeat of earlier results")
                stopped_early = page <= total
                break
            seen.update(page_ids)
            counts.update(store.process_page(parsed.listings))
            _apply_counts(run, counts, len(seen))
            session.add(run)
            session.commit()
            page += 1
        # Only a full, trustworthy crawl may mark unseen ads as removed.
        complete = not stopped_early and total <= max_pages and _plausible(store, scraper.name, contract, seen)
        if complete:
            store.finalize_missing(scraper.name, contract, seen)
        run.status = "ok"
    except (FetchError, ScraperError) as exc:
        log.error("[%s/%s] %s", scraper.name, contract, exc)
        run.status, run.error = "error", str(exc)[:1000]
    except Exception as exc:
        log.exception("[%s/%s] unexpected failure", scraper.name, contract)
        run.status, run.error = "error", f"{type(exc).__name__}: {exc}"[:1000]
    _apply_counts(run, counts, len(seen))
    run.finished_at = utcnow()
    session.add(run)
    session.commit()
    log.info("[%s/%s] %s found=%d new=%d merged/updated=%d skipped=%d%s",
             scraper.name, contract, run.status, run.found, run.new, run.updated, run.skipped,
             "" if complete else " (incomplete: removals not checked)")
    return run


MIN_SEEN_RATIO = 0.5


def _plausible(store: ListingStore, source: str, contract: str, seen: set[str]) -> bool:
    """A crawl that suddenly finds far fewer ads than we track is more likely broken than real."""
    active = store.active_link_count(source, contract)
    if active and len(seen) < active * MIN_SEEN_RATIO:
        log.warning("[%s/%s] only %d ads seen vs %d active: not marking removals", source, contract, len(seen), active)
        return False
    return True


def _apply_counts(run: ScrapeRun, counts: Counter, found: int) -> None:
    run.found = found
    run.new = counts["new"]
    run.updated = counts["updated"] + counts["merged"]
    run.skipped = counts["skipped"] + counts["errors"]


def _close_interrupted_runs(session: Session) -> None:
    """Runs still 'running' belong to a crawl that was killed before finishing."""
    for run in session.exec(select(ScrapeRun).where(ScrapeRun.status == "running")).all():
        run.status, run.error = "error", "interrotto"
        run.finished_at = run.finished_at or utcnow()
        session.add(run)
    session.commit()


def run_all(
    scrapers: Iterable[Scraper],
    contracts: Iterable[Contract] = CONTRACTS,
    max_pages: int = config.MAX_PAGES_PER_SEARCH,
    fetchers: Optional[Fetchers] = None,
) -> list[ScrapeRun]:
    init_db()
    geo = CascinaGeo.from_config()
    images = ImageClient()
    fetchers = fetchers or Fetchers()
    runs: list[ScrapeRun] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            _close_interrupted_runs(session)
            geocoder = NominatimGeocoder(geo.bounds, session)
            try:
                store = ListingStore(session, geo, geocoder, images)
                for scraper in scrapers:
                    for contract in contracts:
                        fetcher = fetchers.for_scraper(scraper)
                        runs.append(crawl_one(scraper, contract, fetcher, store, session, max_pages))
            finally:
                geocoder.close()
    finally:
        fetchers.close()
        images.close()
    return runs
