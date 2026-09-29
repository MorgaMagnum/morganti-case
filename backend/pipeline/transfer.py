"""Export every listing to one CSV file, and import such a file.

The export lets a read-only copy of the app (e.g. on another PC) show exactly the same
results without crawling. Import merges instead of replacing: a listing is matched
through its portal ads (source + external id), newer data wins over older data, and
nothing is ever deleted. Importing an old file therefore never rolls anything back.
"""

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, or_
from sqlmodel import Session, select

from app.models import Listing, ListingImage, SourceLink
from pipeline.store import PRECISION_RANK, replace_images

log = logging.getLogger(__name__)

DELIMITER = ";"  # what Excel expects with Italian regional settings
MAX_ROWS = 50_000
MAX_LINKS = 50
MAX_PHOTOS = 100
MAX_URL = 2_000
MAX_TEXT = 20_000
MAX_ERRORS_REPORTED = 20

COLUMNS = [
    "id", "contratto", "tipologia", "titolo", "prezzo", "superficie_m2", "locali", "bagni", "piano",
    "indirizzo", "frazione", "lat", "lng", "precisione_posizione", "agenzia", "privato", "online",
    "pubblicato_il", "visto_la_prima_volta", "visto_l_ultima_volta", "descrizione", "annunci", "foto",
]
REQUIRED = ("contratto", "tipologia", "titolo", "visto_l_ultima_volta", "annunci")
CONTRACTS = ("vendita", "affitto")
# Excel runs cells starting with these as formulas: a title like "=HYPERLINK(...)" must stay text.
FORMULA_START = ("=", "+", "-", "@")
_SOURCE_RE = re.compile(r"^[a-z0-9_]{1,40}$")


class ImportFileError(ValueError):
    """The file as a whole cannot be imported (wrong format, missing columns...)."""


@dataclass
class ImportResult:
    rows: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    error_count: int = 0

    def add_error(self, message: str) -> None:
        self.error_count += 1
        if len(self.errors) < MAX_ERRORS_REPORTED:
            self.errors.append(message)


# ---- export -----------------------------------------------------------------

def export_csv(session: Session) -> str:
    listings = session.exec(select(Listing).order_by(Listing.id)).all()
    links_by_listing: dict[int, list[SourceLink]] = {}
    for link in session.exec(select(SourceLink).order_by(SourceLink.id)).all():
        links_by_listing.setdefault(link.listing_id, []).append(link)
    photos_by_listing: dict[int, list[str]] = {}
    for img in session.exec(select(ListingImage).order_by(ListingImage.listing_id, ListingImage.position)).all():
        photos_by_listing.setdefault(img.listing_id, []).append(img.source_url)

    out = io.StringIO()
    writer = csv.writer(out, delimiter=DELIMITER, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for listing in listings:
        links = links_by_listing.get(listing.id, [])
        if not links:
            continue  # cannot be matched on import
        writer.writerow(_export_row(listing, links, photos_by_listing.get(listing.id, [])))
    return out.getvalue()


def _export_row(listing: Listing, links: list[SourceLink], photos: list[str]) -> list[Any]:
    has_private = any(l.is_private and l.is_active for l in links)
    return [
        listing.id,
        listing.contract,
        _text_out(listing.property_type),
        _text_out(listing.title),
        _num_out(listing.price),
        _num_out(listing.surface_m2),
        _num_out(listing.rooms),
        _num_out(listing.bathrooms),
        _text_out(listing.floor),
        _text_out(listing.address),
        _text_out(listing.frazione),
        _num_out(listing.lat),
        _num_out(listing.lng),
        listing.geo_precision,
        _text_out(listing.agency_name),
        "si" if has_private else "no",
        "si" if listing.is_active else "no",
        _dt_out(listing.published_at),
        _dt_out(listing.first_seen_at),
        _dt_out(listing.last_seen_at),
        _text_out(listing.description),
        json.dumps([_link_out(l) for l in links], ensure_ascii=False),
        json.dumps(photos, ensure_ascii=False),
    ]


def _link_out(link: SourceLink) -> dict:
    return {
        "fonte": link.source,
        "id": link.external_id,
        "url": link.url,
        "agenzia": link.agency_name,
        "privato": link.is_private,
        "prezzo": link.price,
        "visto_la_prima_volta": _dt_out(link.first_seen_at),
        "visto_l_ultima_volta": _dt_out(link.last_seen_at),
        "online": link.is_active,
    }


def _text_out(value: Optional[str]) -> str:
    if not value:
        return ""
    return "'" + value if value.startswith(FORMULA_START) else value


def _num_out(value) -> str:
    return "" if value is None else str(value)


def _dt_out(value: Optional[datetime]) -> str:
    return _utc(value).strftime("%Y-%m-%dT%H:%M:%SZ") if value else ""


def _utc(value: datetime) -> datetime:
    """Stored datetimes are UTC; SQLite may hand them back without a timezone."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


# ---- import -----------------------------------------------------------------

@dataclass
class _Link:
    source: str
    external_id: str
    url: str
    agency_name: Optional[str]
    is_private: Optional[bool]
    price: Optional[int]
    first_seen_at: Optional[datetime]
    last_seen_at: datetime
    is_active: bool


@dataclass
class _Row:
    fields: dict[str, Any]  # Listing attributes
    links: list[_Link]
    photos: list[str]


def import_csv(session: Session, text: str) -> ImportResult:
    text = text.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text), delimiter=_sniff_delimiter(text))
    result = ImportResult()
    try:
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ImportFileError(f"Il file non è un'esportazione di Cerca Case: manca la colonna \"{missing[0]}\".")
        for line_no, raw in enumerate(reader, start=2):
            result.rows += 1
            if result.rows > MAX_ROWS:
                raise ImportFileError(f"Il file ha più di {MAX_ROWS} righe.")
            try:
                row = _parse_row(raw)
            except ValueError as exc:
                result.add_error(f"Riga {line_no}: {exc}")
                continue
            outcome = _merge(session, row)
            setattr(result, outcome, getattr(result, outcome) + 1)
        session.commit()
    except csv.Error as exc:
        session.rollback()
        raise ImportFileError(f"Il file non è un CSV valido: {exc}") from exc
    except Exception:
        session.rollback()
        raise
    log.info("import: %d rows, %d new, %d updated, %d unchanged, %d errors",
             result.rows, result.new, result.updated, result.unchanged, result.error_count)
    return result


def _sniff_delimiter(text: str) -> str:
    """Accept a file re-saved with commas (e.g. by a spreadsheet with English settings)."""
    header = text.split("\n", 1)[0]
    return "," if header.count(",") > header.count(DELIMITER) else DELIMITER


def _merge(session: Session, row: _Row) -> str:
    local_links = _find_links(session, row.links)
    listing = session.get(Listing, next(iter(local_links.values())).listing_id) if local_links else None
    if listing is None:
        listing = Listing(**row.fields)
        session.add(listing)
        session.flush()
        outcome = "new"
    elif row.fields["last_seen_at"] > _utc(listing.last_seen_at):
        first_seen = min(_utc(listing.first_seen_at), row.fields["first_seen_at"])
        for name, value in row.fields.items():
            setattr(listing, name, value)
        listing.first_seen_at = first_seen
        session.add(listing)
        outcome = "updated"
    else:
        outcome = "unchanged"

    for link in row.links:
        local = local_links.get((link.source, link.external_id))
        if local is None:
            session.add(SourceLink(listing_id=listing.id, **_link_fields(link)))
        elif link.last_seen_at > _utc(local.last_seen_at):
            for name, value in _link_fields(link).items():
                setattr(local, name, value)
            session.add(local)
    if outcome != "unchanged" and row.photos:
        replace_images(session, listing.id, row.photos)
    session.flush()
    return outcome


def _find_links(session: Session, links: list[_Link]) -> dict[tuple[str, str], SourceLink]:
    keys = or_(*(and_(SourceLink.source == l.source, SourceLink.external_id == l.external_id) for l in links))
    return {(l.source, l.external_id): l for l in session.exec(select(SourceLink).where(keys)).all()}


def _link_fields(link: _Link) -> dict:
    return dict(
        source=link.source,
        external_id=link.external_id,
        url=link.url,
        agency_name=link.agency_name,
        is_private=link.is_private,
        price=link.price,
        first_seen_at=link.first_seen_at or link.last_seen_at,
        last_seen_at=link.last_seen_at,
        is_active=link.is_active,
    )


# ---- row validation ------------------------------------------------------------

def _parse_row(raw: dict[str, Optional[str]]) -> _Row:
    def get(name: str) -> str:
        value = raw.get(name)
        return value.strip() if isinstance(value, str) else ""

    contract = get("contratto").lower()
    if contract not in CONTRACTS:
        raise ValueError(f"contratto \"{contract}\" non valido")
    title = _text_in(get("titolo"), 500)
    if not title:
        raise ValueError("titolo mancante")
    last_seen = _dt_in(get("visto_l_ultima_volta"))
    if last_seen is None:
        raise ValueError("data \"visto_l_ultima_volta\" mancante")
    precision = get("precisione_posizione")
    fields = dict(
        contract=contract,
        property_type=_text_in(get("tipologia"), 100) or "altro",
        title=title,
        description=_text_in(get("descrizione"), MAX_TEXT),
        price=_int_in(get("prezzo"), "prezzo"),
        surface_m2=_int_in(get("superficie_m2"), "superficie_m2"),
        rooms=_int_in(get("locali"), "locali"),
        bathrooms=_int_in(get("bagni"), "bagni"),
        floor=_text_in(get("piano"), 100),
        address=_text_in(get("indirizzo"), 300),
        frazione=_text_in(get("frazione"), 100),
        lat=_float_in(get("lat"), "lat", 90),
        lng=_float_in(get("lng"), "lng", 180),
        geo_precision=precision if precision in PRECISION_RANK else "comune",
        agency_name=_text_in(get("agenzia"), 300),
        published_at=_dt_in(get("pubblicato_il")),
        first_seen_at=_dt_in(get("visto_la_prima_volta")) or last_seen,
        last_seen_at=last_seen,
        is_active=get("online").lower() != "no",
    )
    return _Row(fields=fields, links=_links_in(get("annunci"), last_seen), photos=_photos_in(get("foto")))


def _links_in(value: str, row_last_seen: datetime) -> list[_Link]:
    items = _json_list(value, "annunci")
    if not items:
        raise ValueError("nessun annuncio collegato")
    links = []
    for item in items[:MAX_LINKS]:
        if not isinstance(item, dict):
            raise ValueError("colonna \"annunci\" non valida")
        source = str(item.get("fonte") or "")
        external_id = str(item.get("id") or "")[:100]
        url = str(item.get("url") or "")
        if not _SOURCE_RE.match(source) or not external_id or not _is_http(url):
            raise ValueError("annuncio collegato senza fonte, id o link valido")
        private = item.get("privato")
        price = item.get("prezzo")
        links.append(_Link(
            source=source,
            external_id=external_id,
            url=url,
            agency_name=_text_in(str(item.get("agenzia") or ""), 300),
            is_private=private if isinstance(private, bool) else None,
            price=_int_in("" if price is None else str(price), "prezzo"),
            first_seen_at=_dt_in(str(item.get("visto_la_prima_volta") or "")),
            last_seen_at=_dt_in(str(item.get("visto_l_ultima_volta") or "")) or row_last_seen,
            is_active=item.get("online") is not False,
        ))
    return links


def _photos_in(value: str) -> list[str]:
    if not value:
        return []
    return [u for u in _json_list(value, "foto")[:MAX_PHOTOS] if isinstance(u, str) and _is_http(u)]


def _json_list(value: str, column: str) -> list:
    try:
        data = json.loads(value) if value else []
    except json.JSONDecodeError:
        raise ValueError(f"colonna \"{column}\" non valida") from None
    if not isinstance(data, list):
        raise ValueError(f"colonna \"{column}\" non valida")
    return data


def _is_http(url: str) -> bool:
    return len(url) <= MAX_URL and url.startswith(("https://", "http://"))


def _text_in(value: str, max_len: int) -> Optional[str]:
    if value.startswith("'") and value[1:2] in FORMULA_START:
        value = value[1:]
    return value[:max_len] or None


def _int_in(value: str, name: str) -> Optional[int]:
    if not value:
        return None
    try:
        number = int(float(value.replace(",", ".")))
    except (ValueError, OverflowError):
        raise ValueError(f"{name} \"{value[:30]}\" non è un numero") from None
    if not 0 <= number <= 1_000_000_000:
        raise ValueError(f"{name} fuori scala")
    return number


def _float_in(value: str, name: str, limit: float) -> Optional[float]:
    if not value:
        return None
    try:
        number = float(value.replace(",", "."))
    except ValueError:
        raise ValueError(f"{name} \"{value[:30]}\" non è un numero") from None
    if not -limit <= number <= limit:
        raise ValueError(f"{name} fuori scala")
    return number


def _dt_in(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"data \"{value[:30]}\" non valida") from None
    return _utc(parsed)
