from scrapers.base import Scraper
from scrapers.casa_it import CasaItScraper
from scrapers.idealista import IdealistaScraper
from scrapers.immobiliare import ImmobiliareScraper
from scrapers.subito import SubitoScraper
from scrapers.wikicasa import WikicasaScraper

# Order matters: sources with exact coordinates and full galleries first, so
# later portals merge into well-located listings.
ALL_SCRAPERS: tuple[Scraper, ...] = (
    ImmobiliareScraper(),
    CasaItScraper(),
    SubitoScraper(),
    WikicasaScraper(),
    IdealistaScraper(),
)

BY_NAME = {s.name: s for s in ALL_SCRAPERS}
SOURCE_LABELS = {s.name: s.label for s in ALL_SCRAPERS}
