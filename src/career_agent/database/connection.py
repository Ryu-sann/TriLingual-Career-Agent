import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url

DEFAULT_URL = "sqlite:///data/career.db"


def database_url(explicit: str | None = None) -> str:
    return explicit or os.environ.get("CAREER_DATABASE_URL") or DEFAULT_URL


def engine_for(url: str):
    parsed = make_url(url)
    if parsed.get_backend_name() not in {"sqlite", "postgresql"}:
        raise ValueError("Only SQLite and PostgreSQL are supported")
    if parsed.get_backend_name() == "sqlite" and parsed.database not in {None, ":memory:"}:
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, echo=False)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def migrate(engine, root: Path, revision: str = "head"):
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)
