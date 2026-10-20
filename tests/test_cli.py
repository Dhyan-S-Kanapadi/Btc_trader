"""Tests for the temporary CLI command stubs."""

import json

import pytest

from trader.cli import main


def test_help_works(capsys) -> None:
    with pytest.raises(SystemExit) as result:
        main(["--help"])

    assert result.value.code == 0
    assert "worker" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["worker", "api", "replay", "report"])
def test_subcommands_log_json_and_exit_nonzero(command: str, capfd) -> None:
    assert main([command]) != 0
    _, stderr = capfd.readouterr()
    payload = json.loads(stderr)

    assert payload["command"] == command
    assert payload["message"].startswith("not implemented yet (issue #")
