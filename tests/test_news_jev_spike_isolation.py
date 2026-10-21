from pathlib import Path


def test_news_jev_spike_is_not_imported_by_production_package() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("src/trader").rglob("*.py")
    )
    assert "spikes.news_jev" not in source
