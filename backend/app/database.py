"""Database engine / session / schema hardening."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):
        # SQLite needs help to behave like a real transactional DB:
        #  * enforce foreign keys,
        #  * BEGIN IMMEDIATE takes the write lock up-front, so read-then-write
        #    sequences are serialised instead of failing with "database is locked".
        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_conn, _):
            dbapi_conn.isolation_level = None
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(engine, "begin")
        def _on_begin(conn):
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# SEC-DATA-03: the ledger and the audit log are append-only. Besides the ORM
# guard, the database itself rejects UPDATE/DELETE, so a SQL-injection bug or a
# rogue script cannot rewrite history.
_IMMUTABLE_TABLES = ("ledger_entries", "audit_log")


def install_immutability_guards(bind: Engine) -> None:
    dialect = bind.dialect.name
    with bind.begin() as conn:
        for table in _IMMUTABLE_TABLES:
            if dialect == "sqlite":
                for op in ("UPDATE", "DELETE"):
                    conn.execute(
                        text(
                            f"CREATE TRIGGER IF NOT EXISTS {table}_no_{op.lower()} "
                            f"BEFORE {op} ON {table} "
                            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
                        )
                    )
            elif dialect == "postgresql":
                conn.execute(
                    text(
                        "CREATE OR REPLACE FUNCTION vp_forbid_mutation() RETURNS trigger AS $$ "
                        "BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END; $$ "
                        "LANGUAGE plpgsql"
                    )
                )
                conn.execute(text(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}"))
                conn.execute(
                    text(
                        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE "
                        f"ON {table} FOR EACH ROW EXECUTE FUNCTION vp_forbid_mutation()"
                    )
                )


def init_db(bind: Engine | None = None) -> None:
    from app import models  # noqa: F401  (register tables)

    bind = bind or engine
    Base.metadata.create_all(bind)
    install_immutability_guards(bind)
