"""Programmatic Alembic commands used by the one-off migration CLI."""

from pathlib import Path

from alembic import command
from alembic.config import Config


def _config(database_url: str) -> Config:
    for root in (Path(__file__).resolve().parents[3], Path.cwd()):
        config_path = root / "alembic.ini"
        if config_path.is_file():
            break
    else:
        raise FileNotFoundError("alembic.ini is required to run migrations")

    config = Config(str(config_path))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def upgrade_head(database_url: str) -> None:
    """Apply all schema revisions using the supplied connection URL."""

    command.upgrade(_config(database_url), "head")


def downgrade_base(database_url: str) -> None:
    """Remove all schema revisions; used by integration tests only."""

    command.downgrade(_config(database_url), "base")
