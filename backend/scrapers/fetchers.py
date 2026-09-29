"""HTTP and real-browser page fetchers with per-site politeness.

The big portals sit behind DataDome/Cloudflare, which reject plain HTTP clients
and headless browsers. `BrowserFetcher` drives the locally installed Chrome in
headed mode with a persistent profile (so challenge cookies survive between runs);
the window is placed off-screen so it doesn't get in the way.
"""

import logging
import random
import time
import urllib.robotparser
from typing import Optional, Protocol
from urllib.parse import urlsplit

import httpx

from app import config

log = logging.getLogger(__name__)


class FetchError(Exception):
    pass


class Fetcher(Protocol):
    def get(self, url: str) -> str: ...
    def close(self) -> None: ...


class _Politeness:
    """Random delay between requests to the same host + robots.txt check."""

    def __init__(self, delay_range: tuple[float, float] = config.REQUEST_DELAY_RANGE) -> None:
        self._delay_range = delay_range
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}

    def wait(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_hit.get(host)
        if last is not None:
            pause = random.uniform(*self._delay_range) - (time.monotonic() - last)
            if pause > 0:
                time.sleep(pause)
        self._last_hit[host] = time.monotonic()

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self._robots:
            self._robots[host] = self._load_robots(f"{parts.scheme}://{host}/robots.txt")
        parser = self._robots[host]
        # If robots.txt is unreachable (often itself behind the bot wall) we proceed.
        return parser is None or parser.can_fetch(config.USER_AGENT, url)

    @staticmethod
    def _load_robots(robots_url: str) -> Optional[urllib.robotparser.RobotFileParser]:
        try:
            resp = httpx.get(robots_url, headers={"User-Agent": config.USER_AGENT}, timeout=15)
        except httpx.HTTPError as exc:
            log.info("robots.txt unreachable (%s): %s", robots_url, exc)
            return None
        if resp.status_code != 200:
            log.info("robots.txt %s -> HTTP %s, assuming allowed", robots_url, resp.status_code)
            return None
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(resp.text.splitlines())
        return parser


class HttpFetcher:
    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": config.USER_AGENT, "Accept-Language": "it-IT,it;q=0.9"},
            follow_redirects=True,
            timeout=30,
        )
        self._polite = _Politeness()

    def get(self, url: str) -> str:
        if not self._polite.allowed(url):
            raise FetchError(f"robots.txt disallows {url}")
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            self._polite.wait(url)
            try:
                resp = self._client.get(url)
                if resp.status_code == 200:
                    return resp.text
                last_exc = FetchError(f"HTTP {resp.status_code} for {url}")
            except httpx.HTTPError as exc:
                last_exc = exc
            time.sleep(2 ** attempt * 3)
        raise FetchError(str(last_exc))

    def close(self) -> None:
        self._client.close()


class BrowserFetcher:
    """Lazily starts one Chrome instance shared by all browser-mode scrapers."""

    CHALLENGE_WAIT_MS = 20_000

    def __init__(self) -> None:
        self._pw = None
        self._ctx = None
        self._page = None
        self._polite = _Politeness()

    def _ensure(self):
        if self._page is not None:
            return self._page
        from playwright.sync_api import sync_playwright

        config.ensure_dirs()
        self._pw = sync_playwright().start()
        args = ["--disable-blink-features=AutomationControlled"]
        if not config.BROWSER_HEADLESS:
            args.append("--window-position=-2400,-2400")
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(config.BROWSER_PROFILE_DIR),
            channel="chrome",
            headless=config.BROWSER_HEADLESS,
            locale="it-IT",
            viewport={"width": 1366, "height": 900},
            args=args,
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self._page

    def get(self, url: str) -> str:
        if not self._polite.allowed(url):
            raise FetchError(f"robots.txt disallows {url}")
        page = self._ensure()
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            self._polite.wait(url)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                self._wait_past_challenge(page)
                return page.content()
            except Exception as exc:  # playwright raises its own error hierarchy
                last_exc = exc
                log.warning("browser fetch failed (%s/3) %s: %s", attempt + 1, url, exc)
                time.sleep(2 ** attempt * 5)
        raise FetchError(f"{url}: {last_exc}")

    def _wait_past_challenge(self, page) -> None:
        """Anti-bot interstitials resolve themselves in a real browser; wait until they're gone."""
        deadline = time.monotonic() + self.CHALLENGE_WAIT_MS / 1000
        while time.monotonic() < deadline:
            title = (page.title() or "").lower()
            html_len = len(page.content())
            blocked = "attention required" in title or "just a moment" in title or html_len < 20_000
            if not blocked:
                page.wait_for_timeout(1_500)  # let hydration data land
                return
            page.wait_for_timeout(1_000)
        raise FetchError(f"still blocked by anti-bot page: {page.url}")

    def close(self) -> None:
        if self._ctx is not None:
            self._ctx.close()
        if self._pw is not None:
            self._pw.stop()
        self._pw = self._ctx = self._page = None
