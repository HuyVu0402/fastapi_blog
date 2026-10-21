"""Validate and back up an existing Part 14 SQLite database before Alembic adoption."""

import argparse
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import MetaData, create_engine, inspect
from sqlalchemy.engine import make_url

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import models  # noqa: E402, F401
from config import settings  # noqa: E402
from database import Base  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upgrade", action="store_true", help="Back up, stamp, and upgrade")
    args = parser.parse_args()
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        parser.error("Only an existing SQLite file is supported.")
    path = Path(url.database).resolve()
    if not path.is_file():
        parser.error("Database does not exist; use uv run alembic upgrade head for a new database.")

    baseline = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(baseline)
    baseline.tables["posts"]._columns.remove(baseline.tables["posts"].c.likes)
    engine = create_engine(url.set(drivername="sqlite"))
    try:
        with engine.connect() as connection:
            if "alembic_version" in inspect(connection).get_table_names():
                parser.error("Database is already versioned; use uv run alembic upgrade head.")
            differences = compare_metadata(MigrationContext.configure(connection), baseline)
            if differences:
                parser.error(f"Schema differs from Part 14; refusing adoption: {differences!r}")
        print("Schema matches the Part 14 baseline.")
        if not args.upgrade:
            return
        backup = path.with_name(f"{path.stem}.pre-alembic-{uuid4().hex}.sqlite3")
        with sqlite3.connect(path) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        print(f"Backup: {backup}")
    finally:
        engine.dispose()

    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "8df23eeb178f")
    command.upgrade(config, "head")
    print("Database upgraded to Part 15.")


if __name__ == "__main__":
    main()
