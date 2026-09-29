from collections.abc import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app import config

# A crawl and the API write to the same file: wait for the lock instead of failing.
engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})


# Crawler threads write concurrently. In WAL mode a transaction that starts as a read
# and later writes fails at once with "database is locked" (BUSY_SNAPSHOT, the busy
# timeout does not apply) if another thread committed in between. Taking the write
# lock up front (BEGIN IMMEDIATE) makes every conflict a plain wait instead.
crawler_engine = create_engine(
    config.DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 120}
)


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    # WAL lets the API read while a scrape run is writing.
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


event.listen(engine, "connect", _sqlite_pragmas)
event.listen(crawler_engine, "connect", _sqlite_pragmas)


@event.listens_for(crawler_engine, "connect")
def _manual_transactions(dbapi_conn, _record) -> None:
    # Stop pysqlite from issuing its own deferred BEGIN, so the event below decides.
    dbapi_conn.isolation_level = None


@event.listens_for(crawler_engine, "begin")
def _begin_immediate(conn) -> None:
    conn.exec_driver_sql("BEGIN IMMEDIATE")


# Columns added after the first release: (table, column, SQL definition).
# create_all() only creates missing tables, so existing databases get them here.
_ADDED_COLUMNS = [
    ("scraperun", "mode", "VARCHAR NOT NULL DEFAULT 'completo'"),
    ("sourcelink", "is_private", "BOOLEAN"),
]


def _migrate(conn) -> None:
    for table, column, definition in _ADDED_COLUMNS:
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if existing and column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    config.ensure_dirs()
    from app import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        _migrate(conn)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
