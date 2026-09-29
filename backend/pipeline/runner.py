"""Crawl every configured site and store the results.

Two modes:
- full ("completo"): every results page of every site. Needed to notice removed ads
  and price changes on older listings.
- quick ("rapido"): sites sorted newest first, stopping at the first page without any
  new ad. Takes about a minute; never marks ads as removed.

Sites are crawled in parallel (one thread, one browser, one politeness budget per
site); writes to the database are serialized by a shared lock in ListingStore so two
portals listing the same property at the same moment cannot create a duplicate.
"""

import logging
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Optional

from sqlmodel import Session, select

from app import config
from app.db import crawler_engine, init_db
from app.models import ScrapeRun, utcnow
from pipeline.geo import CascinaGeo
from pipeline.geocode import NominatimGeocoder
from pipeline.images import ImageClient
from pipeline.store import ListingStore
from scrapers.base import CONTRACTS, Contract, Scraper, ScraperError
from scrapers.fetchers import BrowserFetcher, Fetcher, FetchError, HttpFetcher

log = logging.getLogger(__name__)

FULL, QUICK = "completo", "rapido"
QUICK_MAX_PAGES = 5  # safety cap: a quick check should never turn into a full crawl
MIN_SEEN_RATIO = 0.5

FetcherFactory = Callable[[Scraper], Fetcher]


def default_fetcher(scraper: Scraper) -> Fetcher:
    # A separate Chrome profile per site: profiles can't be shared between browsers.
    return HttpFetcher() if scraper.fetch_mode == "http" else BrowserFetcher(profile_name=scraper.name)


def crawl_one(
    scraper: Scraper,
    contract: Contract,
    fetcher: Fetcher,
    store: ListingStore,
    session: Session,
    max_pages: int,
    quick: bool = False,
) -> ScrapeRun:
    run = ScrapeRun(source=scraper.name, contract=contract, mode=QUICK if quick else FULL)
    session.add(run)
    session.commit()
    counts: Counter = Counter()
    seen: set[str] = set()
    complete = False
    page_cap = min(max_pages, QUICK_MAX_PAGES) if quick else max_pages
    try:
        page, total = 1, 1
        stopped_early = False
        while page <= min(total, page_cap):
            url = scraper.search_url(contract, page, newest_first=quick)
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
            page_counts = store.process_page(parsed.listings)
            counts.update(page_counts)
            _apply_counts(run, counts, len(seen))
            session.add(run)
            session.commit()
            if quick and page_counts["new"] + page_counts["merged"] == 0:
                log.info("[%s/%s] no new ads on page %d, quick check done", scraper.name, contract, page)
                break
            page += 1
        # Only a full, trustworthy crawl may mark unseen ads as removed.
        complete = (
            not quick
            and not stopped_early
            and total <= max_pages
            and _plausible(store, scraper.name, contract, seen)
        )
        # End the read transaction: it holds the write lock (BEGIN IMMEDIATE), and
        # finalize_missing may now wait for another thread that needs it.
        session.commit()
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
             "" if complete else " (removals not checked)")
    return run


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


def _crawl_source(
    scraper: Scraper,
    contracts: tuple[Contract, ...],
    max_pages: int,
    quick: bool,
    geo: CascinaGeo,
    images: ImageClient,
    write_lock: threading.Lock,
    fetcher_factory: FetcherFactory,
) -> list[ScrapeRun]:
    """One site, all contracts, in its own thread with its own session and browser."""
    fetcher = fetcher_factory(scraper)
    try:
        with Session(crawler_engine, expire_on_commit=False) as session:
            geocoder = NominatimGeocoder(geo.bounds, session)
            try:
                store = ListingStore(session, geo, geocoder, images, write_lock=write_lock)
                return [crawl_one(scraper, c, fetcher, store, session, max_pages, quick) for c in contracts]
            finally:
                geocoder.close()
    finally:
        try:
            fetcher.close()
        except Exception:  # closing must never mask the real outcome
            log.exception("[%s] error closing fetcher", scraper.name)


def run_all(
    scrapers: Iterable[Scraper],
    contracts: Iterable[Contract] = CONTRACTS,
    max_pages: int = config.MAX_PAGES_PER_SEARCH,
    quick: bool = False,
    fetcher_factory: Optional[FetcherFactory] = None,
) -> list[ScrapeRun]:
    init_db()
    scrapers, contracts = list(scrapers), tuple(contracts)
    with Session(crawler_engine) as session:
        _close_interrupted_runs(session)
    geo = CascinaGeo.from_config()
    images = ImageClient()
    write_lock = threading.Lock()
    factory = fetcher_factory or default_fetcher
    try:
        with ThreadPoolExecutor(max_workers=max(1, len(scrapers)), thread_name_prefix="crawl") as pool:
            futures = [
                pool.submit(_crawl_source, s, contracts, max_pages, quick, geo, images, write_lock, factory)
                for s in scrapers
            ]
            runs: list[ScrapeRun] = []
            for scraper, future in zip(scrapers, futures):
                try:
                    runs.extend(future.result())
                except Exception as exc:  # e.g. the browser could not start at all
                    log.exception("[%s] crawl aborted", scraper.name)
                    runs.extend(_failed_runs(scraper, contracts, quick, exc))
            return runs
    finally:
        images.close()


def _failed_runs(scraper: Scraper, contracts: tuple[Contract, ...], quick: bool, exc: Exception) -> list[ScrapeRun]:
    with Session(crawler_engine, expire_on_commit=False) as session:
        runs = [
            ScrapeRun(source=scraper.name, contract=c, mode=QUICK if quick else FULL, status="error",
                      finished_at=utcnow(), error=f"{type(exc).__name__}: {exc}"[:1000])
            for c in contracts
        ]
        session.add_all(runs)
        session.commit()
        return runs
