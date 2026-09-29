"""Gallery images are downloaded on first view and then served from disk."""

import logging
import threading
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Session

from app import config
from app.db import get_session
from app.models import ListingImage
from pipeline.images import ImageClient, image_relpath, is_http_url, open_image, save_jpeg

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["images"])
SessionDep = Annotated[Session, Depends(get_session)]

_client_lock = threading.Lock()
_client: ImageClient | None = None

CACHE_HEADERS = {"Cache-Control": "public, max-age=604800"}
GALLERY_MAX_WIDTH = 1600


def _image_client() -> ImageClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = ImageClient()
        return _client


@router.get("/images/{image_id}")
def get_image(image_id: int, session: SessionDep):
    image = session.get(ListingImage, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Immagine non trovata")

    if image.local_path:
        path = config.MEDIA_DIR / image.local_path
        if path.exists():
            return FileResponse(path, media_type="image/jpeg", headers=CACHE_HEADERS)

    data = _image_client().fetch(image.source_url)
    img = open_image(data) if data else None
    if img is None:
        # Let the browser try the original URL directly (only ever an http(s) CDN link).
        if is_http_url(image.source_url):
            return RedirectResponse(image.source_url, status_code=302)
        raise HTTPException(status_code=404, detail="Immagine non disponibile")

    rel = image_relpath(image.listing_id, image.id)
    try:
        save_jpeg(img, config.MEDIA_DIR / rel, max_width=GALLERY_MAX_WIDTH)
    except OSError:
        log.exception("cannot cache image %s", image.id)
        return RedirectResponse(image.source_url, status_code=302)
    image.local_path = rel
    session.add(image)
    session.commit()
    return FileResponse(config.MEDIA_DIR / rel, media_type="image/jpeg", headers=CACHE_HEADERS)
