from pathlib import Path


def test_agentcore_spike_is_not_imported_by_production_package() -> None:
    files = Path("src/trader").rglob("*.py")
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "spikes.agentcore" not in source
