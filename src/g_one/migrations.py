from pathlib import Path

from alembic import command
from alembic.config import Config


def upgrade_database(database_url: str) -> None:
    """Upgrade the configured database to the schema shipped with this build."""
    project_root = Path(__file__).resolve().parents[2]
    config = Config(project_root / "alembic.ini")
    # ConfigParser treats percent signs in URLs as interpolation. Passing the
    # value through attributes preserves generated passwords byte-for-byte.
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
