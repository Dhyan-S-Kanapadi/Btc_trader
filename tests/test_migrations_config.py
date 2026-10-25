from pathlib import Path

from trader.db import migrations


def test_config_uses_working_directory_when_package_root_has_no_alembic_ini(
    monkeypatch,
    tmp_path: Path,
) -> None:
    installed_module = (
        tmp_path
        / "installed"
        / "lib"
        / "python3.12"
        / "site-packages"
        / "trader"
        / "db"
        / "migrations.py"
    )
    installed_module.parent.mkdir(parents=True)
    config_path = tmp_path / "alembic.ini"
    config_path.write_text("[alembic]\nscript_location = migrations\n", encoding="utf-8")
    monkeypatch.setattr(migrations, "__file__", str(installed_module))
    monkeypatch.chdir(tmp_path)

    config = migrations._config("postgresql+psycopg://paper:password@db/paper_trader")

    assert config.config_file_name == str(config_path)
