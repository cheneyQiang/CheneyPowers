"""CLI entry point for CheneyPowers.

Implements ``cheneypowers {install,uninstall,status}`` plus ``--version``.

Exit codes:

* 0 — success
* 1 — generic error
* 2 — legacy: target already exists in an unrecognised form
* 3 — the ``claude`` CLI is unavailable
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from . import installer as deployer
from .installer import EXIT_GENERIC, EXIT_OK, InstallError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cheneypowers",
        description=(
            "CheneyPowers — register the bundled Claude Code plugin via the "
            "`claude` CLI."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"cheneypowers {__version__}",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # install ---------------------------------------------------------------
    p_install = sub.add_parser(
        "install",
        help="Register the plugin marketplace and install the plugin via the Claude CLI.",
    )
    p_install.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Marketplace source directory (default: the payload shipped with this package).",
    )
    p_install.add_argument(
        "--scope",
        choices=["user", "project", "local"],
        default="user",
        help="Claude Code scope to install into (default: user).",
    )
    p_install.add_argument(
        "--force",
        action="store_true",
        help="Tear down any prior registration first, then re-add. Useful during development.",
    )
    p_install.set_defaults(func=_cmd_install)

    # uninstall -------------------------------------------------------------
    p_uninstall = sub.add_parser(
        "uninstall",
        help="Remove the plugin and the registered marketplace.",
    )
    p_uninstall.add_argument(
        "--force",
        action="store_true",
        help="Reserved for future use; kept for backward compatibility.",
    )
    p_uninstall.set_defaults(func=_cmd_uninstall)

    # status ----------------------------------------------------------------
    p_status = sub.add_parser(
        "status",
        help="Show package version, marketplace source, registration, and plugin enablement.",
    )
    p_status.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Inspect a custom marketplace source directory.",
    )
    p_status.set_defaults(func=_cmd_status)

    return parser


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _cmd_install(args: argparse.Namespace) -> int:
    result = deployer.install(source=args.source, scope=args.scope, force=args.force)
    print("✅ CheneyPowers installed.")
    print(f"   source      : {result.source}")
    print(f"   marketplace : {result.marketplace}")
    print(f"   plugin      : {result.plugin}@{result.marketplace}")
    print(f"   scope       : {result.scope}")
    if result.legacy_cleaned is not None:
        print(
            f"   note        : removed obsolete v0.1.x deployment at "
            f"{result.legacy_cleaned}"
        )
    print(
        "\nOpen a new Claude Code session (or restart Claude Code) for the "
        "plugin to load."
    )
    return EXIT_OK


def _cmd_uninstall(args: argparse.Namespace) -> int:
    removed = deployer.uninstall(force=args.force)
    if removed:
        print(
            f"✅ Removed plugin '{deployer.PLUGIN_NAME}' and marketplace "
            f"'{deployer.MARKETPLACE_NAME}'."
        )
    else:
        print("ℹ️  Nothing to remove — plugin and marketplace were not registered.")
    return EXIT_OK


def _cmd_status(args: argparse.Namespace) -> int:
    info = deployer.status(source=args.source)

    icons = {
        "healthy": "✅",
        "partial": "⚠️",
        "missing": "—",
        "claude-cli-missing": "❌",
    }
    health_icon = icons.get(info["health"], "?")

    def yn(value: bool) -> str:
        return "✅ yes" if value else "—  no"

    bar = "─" * 64
    print(bar)
    print(f"  package version       : {info['package_version']}")
    print(f"  marketplace source    : {info['source']}")
    print(f"  marketplace name      : {info['marketplace']}")
    print(f"  marketplace registered: {yn(info['marketplace_registered'])}")
    print(f"  plugin name           : {info['plugin']}")
    print(f"  plugin enabled        : {yn(info['plugin_enabled'])}")
    print(f"  scope                 : {info['scope']}")
    print(f"  overall health        : {health_icon} {info['health']}")
    if info["legacy_target_present"]:
        print(
            "  legacy v0.1 path      : ⚠️  ~/.claude/plugins/cheneypowers still "
            "present — rerun `cheneypowers install` to clean it up"
        )
    if not info["cli_available"]:
        print(
            "\n❌  The `claude` CLI is not on PATH. Install Claude Code or "
            "set CHENEYPOWERS_CLAUDE_BIN to its absolute path."
        )
    print(bar)

    if info["health"] == "partial":
        print(
            "\n⚠️  Registration is partial. Run `cheneypowers install --force` "
            "to reset."
        )
    elif info["health"] == "missing":
        print("\nRun `cheneypowers install` to register the plugin.")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("\naborted.", file=sys.stderr)
        return EXIT_GENERIC


if __name__ == "__main__":
    raise SystemExit(main())
