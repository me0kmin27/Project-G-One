from pathlib import Path

from alembic import command
from alembic.config import Config


def migration_directory() -> Path:
    """Return migration assets bundled alongside the installed package."""
    return Path(__file__).resolve().with_name("alembic")


def upgrade_database(database_url: str) -> None:
    """Upgrade the configured database to the schema shipped with this build."""
    scripts = migration_directory()
    if not (scripts / "env.py").is_file():
        raise RuntimeError(f"Alembic migration assets are missing: {scripts}")

    # Do not depend on the process working directory or a source-tree
    # alembic.ini. Production imports this module from site-packages while the
    # container working directory is /app.
    config = Config()
    config.set_main_option("script_location", str(scripts))
    # Passing the URL through attributes avoids ConfigParser interpolation when
    # generated database passwords contain percent signs.
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
