"""Image download, resize-for-cover and perceptual hashing."""

import io
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

from app import config

log = logging.getLogger(__name__)

MAX_BYTES = 15 * 1024 * 1024
COVER_MAX_WIDTH = 720
DOWNLOAD_WORKERS = 8


def is_http_url(url: str) -> bool:
    return urlsplit(url).scheme in ("http", "https")


class ImageClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": config.USER_AGENT, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"},
            follow_redirects=True,
            timeout=30,
        )

    def fetch(self, url: str) -> Optional[bytes]:
        if not is_http_url(url):
            return None
        try:
            with self._client.stream("GET", url) as resp:
                if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image/"):
                    log.info("image download %s -> HTTP %s", url, resp.status_code)
                    return None
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        log.info("image too large, skipped: %s", url)
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            log.info("image download failed %s: %s", url, exc)
            return None

    def fetch_many(self, urls: Iterable[str]) -> dict[str, Optional[bytes]]:
        unique = list(dict.fromkeys(urls))
        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            return dict(zip(unique, pool.map(self.fetch, unique)))

    def close(self) -> None:
        self._client.close()


def open_image(data: bytes) -> Optional[Image.Image]:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None


def phash_hex(img: Image.Image) -> str:
    import imagehash  # heavy (numpy/scipy): only the crawler needs it, not the read-only app

    return str(imagehash.phash(img))


def save_jpeg(img: Image.Image, dest: Path, max_width: Optional[int] = None) -> None:
    """Write atomically, so a concurrent reader never sees a half-written file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = img.convert("RGB")
    if max_width and out.width > max_width:
        out = out.resize((max_width, round(out.height * max_width / out.width)), Image.LANCZOS)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as fh:
            out.save(fh, "JPEG", quality=82, optimize=True)
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def cover_relpath(listing_id: int) -> str:
    return f"{listing_id}/cover.jpg"


def image_relpath(listing_id: int, image_id: int) -> str:
    return f"{listing_id}/{image_id}.jpg"
