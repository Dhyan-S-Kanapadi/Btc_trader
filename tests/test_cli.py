"""Tests for the temporary CLI command stubs."""

import json

import pytest

from trader.cli import main


def test_help_works(capsys) -> None:
    with pytest.raises(SystemExit) as result:
        main(["--help"])

    assert result.value.code == 0
    assert "worker" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["worker", "api"])
def test_subcommands_log_json_and_exit_nonzero(command: str, capfd) -> None:
    assert main([command]) != 0
    _, stderr = capfd.readouterr()
    payload = json.loads(stderr)

    assert payload["command"] == command
    assert payload["message"].startswith("not implemented yet (issue #")


def test_synthetic_replay_writes_stable_labeled_files(tmp_path, capfd) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert main(["replay", "--bars", "120", "--output-dir", str(first)]) == 0
    assert main(["replay", "--bars", "120", "--output-dir", str(second)]) == 0
    assert (first / "SYNTHETIC_run_summary.json").read_bytes() == (
        second / "SYNTHETIC_run_summary.json"
    ).read_bytes()
    assert b"SYNTHETIC" in (first / "SYNTHETIC_run_summary.json").read_bytes()
    _, stderr = capfd.readouterr()
    assert '"source":"SYNTHETIC"' in stderr
