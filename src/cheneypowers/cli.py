"""CLI entry point for CheneyPowers.

Implements ``cheneypowers {install,uninstall,status}`` plus ``--version``.
Exit codes follow PRD §5.4:

* 0 — success
* 1 — generic error
* 2 — target already exists and is not managed (use ``--force``)
* 3 — unsupported deployment mode for this platform
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__, payload_dir
from . import installer as deployer
from .installer import (
    EXIT_GENERIC,
    EXIT_OK,
    InstallError,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cheneypowers",
        description=(
            "CheneyPowers — install / uninstall / inspect the Claude Code "
            "plugin payload shipped with this Python package."
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
        help="Deploy the plugin payload into Claude Code's plugins directory.",
    )
    p_install.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Override deployment target (default: ~/.claude/plugins/cheneypowers).",
    )
    p_install.add_argument(
        "--mode",
        choices=["auto", "symlink", "junction", "copy"],
        default="auto",
        help="Deployment mode. 'auto' picks the best available for your OS.",
    )
    p_install.add_argument(
        "--force",
        action="store_true",
        help="If the target already exists and is not managed by us, "
             "back it up and replace it instead of failing.",
    )
    p_install.set_defaults(func=_cmd_install)

    # uninstall -------------------------------------------------------------
    p_uninstall = sub.add_parser(
        "uninstall",
        help="Remove a previously-installed CheneyPowers deployment.",
    )
    p_uninstall.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Override deployment target.",
    )
    p_uninstall.add_argument(
        "--force",
        action="store_true",
        help="Delete the target even if it does not look like a "
             "CheneyPowers deployment.",
    )
    p_uninstall.set_defaults(func=_cmd_uninstall)

    # status ----------------------------------------------------------------
    p_status = sub.add_parser(
        "status",
        help="Show package version, payload path, install target, mode, and link health.",
    )
    p_status.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Inspect a custom target path.",
    )
    p_status.set_defaults(func=_cmd_status)

    return parser


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _cmd_install(args: argparse.Namespace) -> int:
    result = deployer.install(target=args.target, mode=args.mode, force=args.force)
    print("✅ CheneyPowers installed.")
    print(f"   target  : {result.target}")
    print(f"   payload : {result.payload}")
    print(f"   mode    : {result.mode}")
    if result.backed_up_to is not None:
        print(f"   backup  : pre-existing target moved to {result.backed_up_to}")
    if result.mode == "copy":
        print(
            "\nℹ️  Mode is 'copy': you must rerun `cheneypowers install` "
            "after every `pip install --upgrade cheneypowers` to refresh "
            "the payload."
        )
    print("\nOpen a new Claude Code session to load the plugin.")
    return EXIT_OK


def _cmd_uninstall(args: argparse.Namespace) -> int:
    removed = deployer.uninstall(target=args.target, force=args.force)
    target = args.target or deployer.default_target()
    if removed:
        print(f"✅ Removed {target}.")
    else:
        print(f"ℹ️  Nothing to remove at {target}.")
    return EXIT_OK


def _cmd_status(args: argparse.Namespace) -> int:
    info = deployer.status(target=args.target)
    health_icon = {
        "healthy": "✅",
        "broken": "⚠️",
        "missing": "—",
    }.get(info["health"], "?")

    bar = "─" * 60
    print(bar)
    print(f"  package version : {info['package_version']}")
    print(f"  payload         : {info['payload']}")
    print(f"  install target  : {info['target']}")
    print(f"  link mode       : {info['mode'] or 'not installed'}")
    print(f"  link healthy    : {health_icon} {info['health']}")
    print(f"  managed by us   : {'yes' if info['managed'] else 'no'}")
    print(bar)

    if info["health"] == "broken":
        print(
            "\n⚠️  The install target exists but its link is broken. This "
            "usually means the Python package was uninstalled (or moved) "
            "without first running `cheneypowers uninstall`. Run "
            "`cheneypowers uninstall` to clean up, then `cheneypowers install` "
            "again."
        )
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

