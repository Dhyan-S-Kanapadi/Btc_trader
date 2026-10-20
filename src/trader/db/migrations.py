"""Programmatic Alembic commands used by the one-off migration CLI."""

from pathlib import Path

from alembic import command
from alembic.config import Config


def _config(database_url: str) -> Config:
    # shortcut: source-tree image only; package migrations as resources for wheel-only use.
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def upgrade_head(database_url: str) -> None:
    """Apply all schema revisions using the supplied connection URL."""

    command.upgrade(_config(database_url), "head")


def downgrade_base(database_url: str) -> None:
    """Remove all schema revisions; used by integration tests only."""

    command.downgrade(_config(database_url), "base")
