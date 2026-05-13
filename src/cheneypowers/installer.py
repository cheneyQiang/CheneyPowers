"""Deployment logic for CheneyPowers.

v0.2 architecture (delegated): rather than placing a symlink under
``~/.claude/plugins/`` (a location Claude Code does *not* scan for plugins),
we delegate to the ``claude`` CLI:

* ``claude plugin marketplace add <repo-path> --scope user``
* ``claude plugin install cheneypowers@cheneypowers-dev --scope user``

Both Claude CLI commands are idempotent and non-interactive, so ``cheneypowers
install`` is safe to rerun.

Public API consumed by ``cli.py``: :func:`install`, :func:`uninstall`,
:func:`status`, :class:`InstallError`, and the ``EXIT_*`` constants.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional

from . import payload_dir

# ---------------------------------------------------------------------------
# Exit codes (kept stable across the v0.1 → v0.2 rewrite)
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_TARGET_OCCUPIED = 2  # legacy: reused for "plugin already present, no --force"
EXIT_UNSUPPORTED_MODE = 3  # repurposed: `claude` CLI not available / too old

# Plugin and marketplace identifiers. The marketplace name **must** match the
# `name` field of `.claude-plugin/marketplace.json`, otherwise `claude plugin
# install <name>@<marketplace>` cannot resolve the plugin.
PLUGIN_NAME = "cheneypowers"
MARKETPLACE_NAME = "cheneypowers-dev"

Scope = Literal["user", "project", "local"]
DEFAULT_SCOPE: Scope = "user"

# Path where v0.1.x used to drop a symlink. We clean it up on install/uninstall
# because it does nothing useful (Claude Code never scanned this location) and
# leaving it behind is just confusing.
_LEGACY_TARGET = Path.home() / ".claude" / "plugins" / PLUGIN_NAME


# ---------------------------------------------------------------------------
# Errors and result type
# ---------------------------------------------------------------------------


class InstallError(RuntimeError):
    """An installer error with an associated CLI exit code."""

    def __init__(self, message: str, exit_code: int = EXIT_GENERIC) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class InstallResult:
    source: Path
    marketplace: str
    plugin: str
    scope: Scope
    legacy_cleaned: Optional[Path] = None


# ---------------------------------------------------------------------------
# `claude` CLI plumbing
# ---------------------------------------------------------------------------


def _claude_bin() -> str:
    """Locate the ``claude`` executable.

    Honors ``CHENEYPOWERS_CLAUDE_BIN`` for non-standard installs. Falls back to
    ``shutil.which("claude")``. Raises :class:`InstallError` with exit code
    :data:`EXIT_UNSUPPORTED_MODE` if neither resolves.
    """
    explicit = os.environ.get("CHENEYPOWERS_CLAUDE_BIN")
    if explicit:
        if not Path(explicit).exists():
            raise InstallError(
                f"CHENEYPOWERS_CLAUDE_BIN points at {explicit!r}, which does "
                "not exist.",
                EXIT_UNSUPPORTED_MODE,
            )
        return explicit
    found = shutil.which("claude")
    if not found:
        raise InstallError(
            "Could not find the `claude` CLI on PATH. Install Claude Code "
            "first (https://docs.anthropic.com/en/docs/claude-code) or set "
            "CHENEYPOWERS_CLAUDE_BIN=/absolute/path/to/claude.",
            EXIT_UNSUPPORTED_MODE,
        )
    return found


def _run_claude(args: List[str]) -> subprocess.CompletedProcess:
    """Run ``claude <args...>`` and return the completed process.

    Errors are not raised here — callers decide how to interpret exit codes
    because some calls (e.g. ``uninstall``) are expected to fail benignly when
    the entity is already absent.
    """
    return subprocess.run(
        [_claude_bin(), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _require_success(proc: subprocess.CompletedProcess, action: str) -> None:
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit code {proc.returncode}"
        raise InstallError(f"`claude {action}` failed: {detail}")


# ---------------------------------------------------------------------------
# Legacy v0.1.x cleanup
# ---------------------------------------------------------------------------


def _looks_like_v01_deployment(target: Path) -> bool:
    """True iff ``target`` looks like our old symlink/copy layout."""
    marker = target / ".claude-plugin" / "plugin.json"
    if not marker.is_file():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return data.get("name") == PLUGIN_NAME


def _cleanup_legacy_target() -> Optional[Path]:
    """Remove ``~/.claude/plugins/cheneypowers/`` if it is our v0.1 leftover.

    Returns the path that was cleaned, or ``None`` if there was nothing to do.
    """
    if not _LEGACY_TARGET.exists() and not _LEGACY_TARGET.is_symlink():
        return None
    if not _looks_like_v01_deployment(_LEGACY_TARGET):
        return None
    if _LEGACY_TARGET.is_symlink():
        _LEGACY_TARGET.unlink()
    elif _LEGACY_TARGET.is_dir():
        shutil.rmtree(_LEGACY_TARGET)
    else:
        _LEGACY_TARGET.unlink()
    return _LEGACY_TARGET


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def install(
    *,
    source: Optional[Path] = None,
    scope: Scope = DEFAULT_SCOPE,
    force: bool = False,
) -> InstallResult:
    """Register the marketplace and install the plugin via the Claude CLI.

    Parameters
    ----------
    source:
        Filesystem path holding the marketplace manifest. Defaults to
        :func:`payload_dir`, which resolves to the bundled
        ``cheneypowers/_payload`` for wheel installs or the repo root for
        editable installs.
    scope:
        ``user`` (default), ``project``, or ``local`` — forwarded to
        ``claude plugin marketplace add`` and ``claude plugin install``.
    force:
        If true, tear down any prior registration first so the marketplace
        source path is refreshed. Useful while developing the plugin.
    """
    src = (source or payload_dir()).resolve()
    manifest = src / ".claude-plugin" / "marketplace.json"
    if not manifest.is_file():
        raise InstallError(
            f"{src} is not a valid plugin source: "
            f"{manifest} does not exist.",
            EXIT_GENERIC,
        )

    legacy = _cleanup_legacy_target()

    if force:
        # Best-effort teardown; ignore errors because the entities might
        # simply not exist yet.
        _run_claude(["plugin", "uninstall", PLUGIN_NAME])
        _run_claude(["plugin", "marketplace", "remove", MARKETPLACE_NAME])

    add = _run_claude(
        ["plugin", "marketplace", "add", str(src), "--scope", scope]
    )
    _require_success(add, "plugin marketplace add")

    install_proc = _run_claude(
        ["plugin", "install", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}", "--scope", scope]
    )
    _require_success(install_proc, "plugin install")

    return InstallResult(
        source=src,
        marketplace=MARKETPLACE_NAME,
        plugin=PLUGIN_NAME,
        scope=scope,
        legacy_cleaned=legacy,
    )


def uninstall(*, scope: Scope = DEFAULT_SCOPE, force: bool = False) -> bool:
    """Tear down the plugin and the marketplace.

    Returns ``True`` if anything was actually removed.
    """
    del scope  # currently unused — Claude CLI infers scope from where it's recorded
    del force  # kept for API stability; no scary path is ever touched

    removed = False

    plugin_proc = _run_claude(["plugin", "uninstall", PLUGIN_NAME])
    if plugin_proc.returncode == 0 and "Successfully" in (plugin_proc.stdout or ""):
        removed = True

    market_proc = _run_claude(["plugin", "marketplace", "remove", MARKETPLACE_NAME])
    if market_proc.returncode == 0 and "Successfully" in (market_proc.stdout or ""):
        removed = True

    legacy = _cleanup_legacy_target()
    if legacy is not None:
        removed = True

    return removed


def status(*, source: Optional[Path] = None) -> dict:
    """Return a dict describing the current registration state."""
    src = (source or payload_dir()).resolve()

    # If the `claude` CLI is missing, surface a partial status instead of
    # crashing — the user might want to see version + payload anyway.
    try:
        mkt = _run_claude(["plugin", "marketplace", "list"])
        plugins = _run_claude(["plugin", "list"])
        cli_available = True
        mkt_out = mkt.stdout or ""
        plugin_out = plugins.stdout or ""
    except InstallError:
        cli_available = False
        mkt_out = ""
        plugin_out = ""

    marketplace_registered = MARKETPLACE_NAME in mkt_out
    plugin_enabled = PLUGIN_NAME in plugin_out
    legacy_present = _LEGACY_TARGET.exists() or _LEGACY_TARGET.is_symlink()

    if not cli_available:
        health = "claude-cli-missing"
    elif marketplace_registered and plugin_enabled:
        health = "healthy"
    elif marketplace_registered or plugin_enabled:
        health = "partial"
    else:
        health = "missing"

    return {
        "package_version": _package_version(),
        "source": src,
        "marketplace": MARKETPLACE_NAME,
        "marketplace_registered": marketplace_registered,
        "plugin": PLUGIN_NAME,
        "plugin_enabled": plugin_enabled,
        "scope": DEFAULT_SCOPE,
        "health": health,
        "legacy_target_present": legacy_present,
        "cli_available": cli_available,
    }


def _package_version() -> str:
    # Late import to avoid a circular reference at module load.
    from . import __version__ as v

    return v
