"""Command line entry point.

    python cli.py scrape                      # all sites, sale + rent
    python cli.py scrape --source subito --contract affitto --max-pages 2
"""

import argparse
import logging
import sys

from app import config
from pipeline.runner import run_all
from scrapers.base import CONTRACTS
from scrapers.registry import ALL_SCRAPERS, BY_NAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="morganti-cerca-case")
    sub = parser.add_subparsers(dest="command", required=True)
    scrape = sub.add_parser("scrape", help="scarica gli annunci da tutti i siti")
    scrape.add_argument("--source", action="append", choices=sorted(BY_NAME), help="solo queste fonti")
    scrape.add_argument("--contract", action="append", choices=CONTRACTS, help="vendita e/o affitto")
    scrape.add_argument("--max-pages", type=int, default=config.MAX_PAGES_PER_SEARCH)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    scrapers = [BY_NAME[name] for name in args.source] if args.source else list(ALL_SCRAPERS)
    runs = run_all(scrapers, tuple(args.contract or CONTRACTS), args.max_pages)

    print("\nRiepilogo:")
    for run in runs:
        print(f"  {run.source:12} {run.contract:8} {run.status:6} pagine={run.pages:3} trovati={run.found:4} "
              f"nuovi={run.new:4} aggiornati={run.updated:4} scartati={run.skipped:4} {run.error or ''}")
    return 0 if all(r.status == "ok" for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
