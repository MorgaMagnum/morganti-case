"""Map each site's vocabulary onto one canonical schema."""

import re
from typing import Optional

PROPERTY_TYPES = (
    "appartamento",
    "attico / mansarda",
    "casa indipendente",
    "villa",
    "villetta a schiera",
    "rustico / casale",
    "stanza",
    "terreno",
    "altro",
)

# keyword -> canonical type. When several keywords occur, the earliest one in
# the text wins ("Appartamento con 2 camere" is a flat, not a room).
_KEYWORDS: dict[str, str] = {
    "appartament": "appartamento",
    "monolocale": "appartamento",
    "bilocale": "appartamento",
    "trilocale": "appartamento",
    "quadrilocale": "appartamento",
    "plurilocale": "appartamento",
    "5 locali": "appartamento",
    "locale": "appartamento",
    "duplex": "appartamento",
    "attico": "attico / mansarda",
    "mansard": "attico / mansarda",
    "loft": "attico / mansarda",
    "terratetto": "casa indipendente",
    "casa": "casa indipendente",
    "viareggina": "casa indipendente",
    "villa": "villa",
    "schiera": "villetta a schiera",
    "rustico": "rustico / casale",
    "casale": "rustico / casale",
    "colonica": "rustico / casale",
    "podere": "rustico / casale",
    "stanza": "stanza",
    "camera": "stanza",
    "posto letto": "stanza",
    "posti-letto": "stanza",
    "terreno": "terreno",
}

# Site categories too broad to decide on their own: look at the title first.
_AMBIGUOUS_FALLBACK = {
    "ville-singole-e-a-schiera": "villa",
    "terreni-e-rustici": "rustico / casale",
}


def _match(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    lowered = text.lower()
    best: tuple[int, int, str] | None = None  # (position, -len(keyword), type)
    for keyword, ptype in _KEYWORDS.items():
        pos = lowered.find(keyword)
        if pos >= 0:
            key = (pos, -len(keyword), ptype)
            if best is None or key < best:
                best = key
    return best[2] if best else None


def canonical_property_type(raw_type: Optional[str], title: Optional[str] = None) -> str:
    if raw_type and raw_type in _AMBIGUOUS_FALLBACK:
        return _match(title) or _AMBIGUOUS_FALLBACK[raw_type]
    return _match(raw_type) or _match(title) or "altro"


_STREET_PREFIX_RE = re.compile(
    r"^(via|viale|v\.le|v\.|piazza|p\.zza|p\.za|largo|corso|c\.so|strada|vicolo|loc\.|localit[aà]|piazzale)\s+",
    re.I,
)


_CAP_RE = re.compile(r"\b\d{5}\b")
_TRAILING_PLACE = {"cascina", "pi", "pisa", "italia", "italy"}


def normalize_address(value: Optional[str]) -> Optional[str]:
    """Comparable form of a street address: no street prefix, CAP/city, punctuation or case.

    'Via Macerata, 145, 56021 Cascina Pi, Italia 145' -> 'macerata 145'
    """
    if not value:
        return None
    text = _CAP_RE.split(value.strip().lower())[0]
    text = _STREET_PREFIX_RE.sub("", text.strip())
    text = text.replace("/", "")  # 3/A -> 3a
    text = re.sub(r"[^\w\s]", " ", text)
    words = text.split()
    while len(words) > 1 and words[-1] in _TRAILING_PLACE:
        words.pop()
    return " ".join(words) or None


def street_key(address_norm: Optional[str]) -> Optional[str]:
    """Street name without the civic number: 'b genovesi sud 73' -> 'b genovesi sud'."""
    if not address_norm:
        return None
    words = address_norm.split()
    while len(words) > 1 and words[-1][:1].isdigit():
        words.pop()
    return " ".join(words)
