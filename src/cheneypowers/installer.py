"""Deployment logic for the CheneyPowers Claude Code plugin.

The installer makes the plugin payload visible to Claude Code by placing it at
``~/.claude/plugins/cheneypowers``. Three deployment modes are supported:

* ``symlink``  — ``os.symlink`` (POSIX, or Windows with Developer Mode)
* ``junction`` — Windows directory junction via ``mklink /J``
* ``copy``     — full directory copy

When mode is ``symlink`` or ``junction``, upgrading the package via pip is
picked up by Claude Code immediately (next session). In ``copy`` mode the user
must rerun ``cheneypowers install`` after every upgrade.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional

from . import payload_dir

# ---------------------------------------------------------------------------
# Exit codes (kept in sync with PRD §5.4)
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_TARGET_OCCUPIED = 2
EXIT_UNSUPPORTED_MODE = 3

DeployMode = Literal["symlink", "junction", "copy", "auto"]
ResolvedMode = Literal["symlink", "junction", "copy"]

DEFAULT_TARGET_NAME = "cheneypowers"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class InstallError(RuntimeError):
    """An installer error with an associated CLI exit code."""

    def __init__(self, message: str, exit_code: int = EXIT_GENERIC) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class InstallResult:
    target: Path
    mode: ResolvedMode
    payload: Path
    backed_up_to: Optional[Path] = None


def default_target() -> Path:
    """``~/.claude/plugins/cheneypowers`` by default."""
    return Path.home() / ".claude" / "plugins" / DEFAULT_TARGET_NAME


def is_windows() -> bool:
    return platform.system() == "Windows"


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def _readlink(path: Path) -> Optional[Path]:
    """Return ``path``'s symlink target, or ``None`` if it isn't a symlink."""
    try:
        if path.is_symlink():
            return Path(os.readlink(path))
    except OSError:
        pass
    return None


def _is_junction(path: Path) -> bool:
    """Return True if ``path`` is a Windows directory junction.

    Junctions are reparse points that are not symlinks; ``Path.is_symlink``
    returns False for them. We probe via ``os.path.realpath`` differing from
    the original path *and* the path being a directory.
    """
    if not is_windows():
        return False
    try:
        if not path.is_dir():
            return False
        return Path(os.path.realpath(path)) != path.resolve(strict=False)
    except OSError:
        return False


def detect_mode(target: Path) -> Optional[ResolvedMode]:
    """Detect how an existing target was deployed.

    The target itself is always a real directory; we look at its
    ``.claude-plugin`` child to figure out whether the payload entries
    inside were deployed via symlink, junction, or copy.
    """
    if not target.exists() or not target.is_dir():
        return None
    probe = target / ".claude-plugin"
    if not probe.exists() and not probe.is_symlink():
        return None
    if probe.is_symlink():
        return "symlink"
    if _is_junction(probe):
        return "junction"
    if probe.is_dir():
        return "copy"
    return None


def is_managed_target(target: Path) -> bool:
    """Heuristic: did *we* create this target?

    A target is "managed" if it points to (or is a copy of) the payload that
    this currently-installed package ships. We check for the marker file
    ``.claude-plugin/plugin.json`` plus matching plugin name.
    """
    marker = target / ".claude-plugin" / "plugin.json"
    if not marker.is_file():
        return False
    try:
        import json

        data = json.loads(marker.read_text(encoding="utf-8"))
        return data.get("name") == DEFAULT_TARGET_NAME
    except (OSError, ValueError):
        return False


def link_health(target: Path) -> str:
    """Return one of: ``healthy`` / ``broken`` / ``missing``.

    The target itself is always a real directory once installed. ``healthy``
    means at least the ``.claude-plugin`` payload entry exists and (if it is
    a symlink/junction) resolves to a real directory.
    """
    if not target.exists() or not target.is_dir():
        return "missing"
    probe = target / ".claude-plugin"
    if not probe.exists() and not probe.is_symlink():
        return "missing"
    if probe.is_symlink():
        try:
            resolved = probe.resolve(strict=True)
        except (OSError, RuntimeError):
            return "broken"
        return "healthy" if resolved.is_dir() else "broken"
    return "healthy" if probe.is_dir() else "broken"


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------


def _resolve_mode(requested: DeployMode) -> ResolvedMode:
    if requested != "auto":
        return _validate_mode(requested)
    # Auto pick: symlink everywhere; if it fails on Windows, install() will
    # fall back to junction, then copy.
    return "symlink"


def _validate_mode(mode: DeployMode) -> ResolvedMode:
    if mode == "junction" and not is_windows():
        raise InstallError(
            "--mode junction is only supported on Windows.",
            EXIT_UNSUPPORTED_MODE,
        )
    if mode in {"symlink", "junction", "copy"}:
        return mode  # type: ignore[return-value]
    raise InstallError(f"Unknown mode: {mode}", EXIT_UNSUPPORTED_MODE)


# ---------------------------------------------------------------------------
# Deploy primitives
# ---------------------------------------------------------------------------


def _ensure_parent(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)


def _remove_existing(target: Path) -> None:
    """Remove a path that we know we own, in any of its forms."""
    if target.is_symlink():
        target.unlink()
        return
    if target.is_dir():
        shutil.rmtree(target)
        return
    if target.exists():
        target.unlink()


def _backup_existing(target: Path) -> Path:
    backup = target.with_name(f"{target.name}.bak.{int(time.time())}")
    target.rename(backup)
    return backup


# Subdirectories that constitute the actual Claude Code plugin payload.
# We deploy each one individually rather than linking the whole payload dir,
# so that editable installs (where payload_dir resolves to the repo root)
# don't leak src/, docs/, tests/, pyproject.toml, etc. into the plugin folder.
_PAYLOAD_ENTRIES = (".claude-plugin", "hooks", "skills", "assets")


def _payload_entries(payload: Path) -> list[Path]:
    entries: list[Path] = []
    for name in _PAYLOAD_ENTRIES:
        candidate = payload / name
        if candidate.exists():
            entries.append(candidate)
    if not entries:
        raise InstallError(
            f"No plugin payload entries found under {payload}. Expected at "
            f"least one of: {', '.join(_PAYLOAD_ENTRIES)}.",
            EXIT_GENERIC,
        )
    return entries


def _do_symlink(target: Path, payload: Path) -> None:
    target.mkdir(parents=True, exist_ok=False)
    for entry in _payload_entries(payload):
        os.symlink(
            str(entry),
            str(target / entry.name),
            target_is_directory=entry.is_dir(),
        )


def _do_junction(target: Path, payload: Path) -> None:
    if not is_windows():
        raise InstallError(
            "Directory junctions are a Windows-only feature.",
            EXIT_UNSUPPORTED_MODE,
        )
    target.mkdir(parents=True, exist_ok=False)
    for entry in _payload_entries(payload):
        # ``mklink /J`` is a cmd.exe builtin; shell=True is required.
        link = target / entry.name
        cmd = f'mklink /J "{link}" "{entry}"'
        completed = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if completed.returncode != 0:
            raise InstallError(
                "mklink /J failed: "
                + (completed.stderr.strip() or completed.stdout.strip() or "unknown error"),
                EXIT_GENERIC,
            )


def _do_copy(target: Path, payload: Path) -> None:
    target.mkdir(parents=True, exist_ok=False)
    for entry in _payload_entries(payload):
        dest = target / entry.name
        if entry.is_dir():
            shutil.copytree(str(entry), str(dest))
        else:
            shutil.copy2(str(entry), str(dest))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def install(
    *,
    target: Optional[Path] = None,
    mode: DeployMode = "auto",
    force: bool = False,
) -> InstallResult:
    """Deploy the plugin payload to ``target``.

    Parameters
    ----------
    target:
        Destination path. Defaults to ``~/.claude/plugins/cheneypowers``.
    mode:
        ``symlink`` | ``junction`` | ``copy`` | ``auto``.
    force:
        If the target already exists and is *not* a managed CheneyPowers
        deployment, ``force=True`` renames it to ``<target>.bak.<ts>``
        instead of failing. A managed target is always replaced.
    """
    payload = payload_dir()
    target = target or default_target()
    _ensure_parent(target)

    backed_up: Optional[Path] = None

    # If target already points at a managed deployment, treat install as
    # idempotent: just refresh it.
    if (target.exists() or target.is_symlink()) and is_managed_target(target):
        _remove_existing(target)
    elif target.exists() or target.is_symlink():
        if not force:
            raise InstallError(
                f"Target {target} already exists and is not a CheneyPowers "
                "deployment. Pass --force to back it up and replace it.",
                EXIT_TARGET_OCCUPIED,
            )
        backed_up = _backup_existing(target)

    resolved = _resolve_mode(mode)
    used = _attempt_deploy(target, payload, resolved, fallback=mode == "auto")

    return InstallResult(target=target, mode=used, payload=payload, backed_up_to=backed_up)


def _attempt_deploy(
    target: Path,
    payload: Path,
    primary: ResolvedMode,
    *,
    fallback: bool,
) -> ResolvedMode:
    chain: Iterable[ResolvedMode]
    if fallback and primary == "symlink" and is_windows():
        chain = ("symlink", "junction", "copy")
    elif fallback and primary == "symlink":
        chain = ("symlink",)  # POSIX: no useful fallback
    elif fallback and primary == "junction":
        chain = ("junction", "copy")
    else:
        chain = (primary,)

    last_error: Optional[BaseException] = None
    for candidate in chain:
        try:
            if candidate == "symlink":
                _do_symlink(target, payload)
            elif candidate == "junction":
                _do_junction(target, payload)
            else:
                _do_copy(target, payload)
            return candidate
        except (OSError, InstallError) as exc:
            last_error = exc
            # Clean any partial result before the next attempt.
            if target.exists() or target.is_symlink():
                try:
                    _remove_existing(target)
                except OSError:
                    pass
            continue

    if isinstance(last_error, InstallError):
        raise last_error
    raise InstallError(
        f"Could not deploy plugin via any of {list(chain)}: {last_error}",
        EXIT_GENERIC,
    )


def uninstall(*, target: Optional[Path] = None, force: bool = False) -> bool:
    """Remove a previously-installed deployment.

    Returns ``True`` if something was removed, ``False`` if there was nothing
    to do.
    """
    target = target or default_target()
    if not target.exists() and not target.is_symlink():
        return False

    if not is_managed_target(target) and not target.is_symlink():
        # A regular directory at our path that isn't ours: refuse without
        # --force to avoid wiping out the user's data.
        if not force:
            raise InstallError(
                f"Refusing to remove {target}: it does not look like a "
                "CheneyPowers deployment. Pass --force to delete anyway.",
                EXIT_TARGET_OCCUPIED,
            )

    _remove_existing(target)
    return True


def status(*, target: Optional[Path] = None) -> dict:
    """Return a dict describing the current deployment state."""
    target = target or default_target()
    payload = payload_dir()
    detected = detect_mode(target)
    return {
        "package_version": _package_version(),
        "payload": payload,
        "target": target,
        "mode": detected,
        "health": link_health(target),
        "managed": is_managed_target(target) if target.exists() else False,
    }


def _package_version() -> str:
    # Defer the import to avoid a circular reference at module-import time.
    from . import __version__ as v

    return v


def python_version_str() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

