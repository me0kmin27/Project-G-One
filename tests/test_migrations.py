from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from g_one import models  # noqa: F401
from g_one.db import Base
from g_one.migrations import upgrade_database


EXPECTED_TABLES = {"alembic_version", "audit_events", "devices", "support_requests"}


def test_upgrade_builds_database_from_scratch(tmp_path):
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    upgrade_database(url)
    assert EXPECTED_TABLES == set(inspect(create_engine(url)).get_table_names())


def test_upgrade_adopts_database_from_pre_migration_release(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    upgrade_database(url)
    assert EXPECTED_TABLES == set(inspect(engine).get_table_names())

    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.check(config)
