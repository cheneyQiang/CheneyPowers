"""CLI entry point for CheneyPowers.

Implements ``cheneypowers {install,uninstall,status}`` plus ``--version``.

Each command takes ``--target`` to select one or more harness platforms:

* ``--target claude`` — Claude Code (default)
* ``--target codex``  — Codex CLI
* ``--target catpaw`` — CatPaw / CatDesk (skill files only, no auto-trigger)
* ``--target all``    — all three

Exit codes:

* 0 — success
* 1 — generic error
* 2 — target already exists and is not managed (use ``--force``)
* 3 — unsupported deployment mode for this platform
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from . import __version__
from . import installer as deployer
from .installer import (
    ALL_TARGETS,
    EXIT_GENERIC,
    EXIT_OK,
    InstallError,
    TargetName,
)


_TARGET_CHOICES = ("claude", "codex", "catpaw", "all")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cheneypowers",
        description=(
            "CheneyPowers — install / uninstall / inspect the CheneyPowers "
            "skills library across Claude Code, Codex, and CatPaw / CatDesk."
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
        help="Deploy the plugin payload into the chosen harness(es).",
    )
    p_install.add_argument(
        "--target",
        choices=_TARGET_CHOICES,
        default="claude",
        help="Which harness to install for. Use 'all' to install everywhere "
             "(default: claude).",
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
        help="If a non-managed deployment already exists at the target, "
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
        choices=_TARGET_CHOICES,
        default="claude",
        help="Which harness to uninstall from. 'all' removes from every "
             "harness (default: claude).",
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
        help="Show install state across all harnesses (or one).",
    )
    p_status.add_argument(
        "--target",
        choices=_TARGET_CHOICES,
        default="all",
        help="Which harness to inspect (default: all).",
    )
    p_status.set_defaults(func=_cmd_status)

    return parser


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _resolve_targets(target_arg: str) -> tuple[TargetName, ...]:
    if target_arg == "all":
        return ALL_TARGETS
    return (target_arg,)  # type: ignore[return-value]


def _cmd_install(args: argparse.Namespace) -> int:
    targets = _resolve_targets(args.target)
    any_failure = False
    for target in targets:
        print(f"\n── Installing to {target} ──")
        try:
            result = deployer.install(target, mode=args.mode, force=args.force)
        except InstallError as exc:
            any_failure = True
            print(f"❌ {target}: {exc}", file=sys.stderr)
            continue
        print(f"✅ CheneyPowers installed for {result.target_name}.")
        print(f"   target  : {result.target_path}")
        print(f"   payload : {result.payload}")
        print(f"   mode    : {result.mode}")
        if result.backed_up_to is not None:
            print(f"   backup  : pre-existing target moved to {result.backed_up_to}")
        if result.mode == "copy":
            print(
                "   ℹ️  Mode is 'copy': rerun `cheneypowers install` after "
                "every package upgrade to refresh the payload."
            )
        if result.extra:
            print(f"   note    : {result.extra}")
    return EXIT_GENERIC if any_failure else EXIT_OK


def _cmd_uninstall(args: argparse.Namespace) -> int:
    targets = _resolve_targets(args.target)
    any_failure = False
    for target in targets:
        try:
            removed = deployer.uninstall(target, force=args.force)
        except InstallError as exc:
            any_failure = True
            print(f"❌ {target}: {exc}", file=sys.stderr)
            continue
        adapter_path = deployer._adapter_for(target).target_path  # noqa: SLF001
        if removed:
            print(f"✅ {target}: removed deployment at {adapter_path}.")
        else:
            print(f"ℹ️  {target}: nothing to remove at {adapter_path}.")
    return EXIT_GENERIC if any_failure else EXIT_OK


def _cmd_status(args: argparse.Namespace) -> int:
    targets = _resolve_targets(args.target)
    rows = [deployer.status_one(t) for t in targets]
    pkg_version = rows[0]["package_version"] if rows else "unknown"
    payload = rows[0]["payload"] if rows else "?"

    bar = "─" * 64
    print(bar)
    print(f"  CheneyPowers {pkg_version}")
    print(f"  payload : {payload}")
    print(bar)
    for row in rows:
        health_icon = {
            "healthy": "✅",
            "broken": "⚠️ ",
            "missing": "—",
        }.get(row["health"], "?")
        managed = "yes" if row["managed"] else "no"
        mode = row["mode"] or "not installed"
        print(f"  {row['target_name']:<7}  {health_icon} {row['health']:<8}  "
              f"mode={mode:<8}  managed={managed}")
        print(f"           path: {row['target_path']}")
    print(bar)

    if any(row["health"] == "broken" for row in rows):
        print(
            "\n⚠️  Some deployments have broken links. Try "
            "`cheneypowers uninstall --target <name>` then `cheneypowers install`."
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
    except KeyboardInterrupt:
        print("\naborted.", file=sys.stderr)
        return EXIT_GENERIC


if __name__ == "__main__":
    raise SystemExit(main())

