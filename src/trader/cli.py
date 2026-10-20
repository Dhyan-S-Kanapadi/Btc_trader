"""Temporary command-line entrypoint for future paper-trading services."""

import argparse
from collections.abc import Sequence

from trader.logging import configure_logging

_COMMAND_ISSUES = {
    "worker": 13,
    "api": 14,
    "replay": 10,
    "report": 12,
}


def build_parser() -> argparse.ArgumentParser:
    """Build the paper-trader CLI parser without implementing any service logic."""

    parser = argparse.ArgumentParser(prog="trader", description="Paper-trading research CLI.")
    subcommands = parser.add_subparsers(dest="command")
    for command in _COMMAND_ISSUES:
        subcommands.add_parser(command, help=f"Reserved for issue #{_COMMAND_ISSUES[command]}.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a stub command and return its process exit status."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    issue = _COMMAND_ISSUES[args.command]
    configure_logging().error(
        f"not implemented yet (issue #{issue})",
        extra={"command": args.command, "issue": issue},
    )
    return 1
