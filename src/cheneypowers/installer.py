"""Deployment logic for the CheneyPowers plugin.

Three target platforms are supported, each with its own adapter:

* ``claude``  — Claude Code: ``~/.claude/plugins/cheneypowers/`` containing
  the four payload entries (``.claude-plugin``, ``hooks``, ``skills``, ``assets``)
  as symlinks back into the source repo.
* ``codex``   — Codex: ``~/.codex/plugins/cheneypowers/`` with the same four
  entries (substituting ``.codex-plugin`` for ``.claude-plugin``). Also
  registers the plugin in ``~/.codex/config.toml`` under
  ``[plugins."cheneypowers@cheneypowers-local"]``.
* ``catpaw``  — CatPaw / CatDesk: each skill is symlinked individually into
  ``~/.catpaw/skills/cheneypowers-<name>/``. CatPaw has no plugin metadata
  format so only the skill files are deployed (auto-trigger via SessionStart
  is not supported on CatPaw — explicit invocation only).

Three deployment modes are supported per target:

* ``symlink``  — ``os.symlink`` (POSIX, or Windows with Developer Mode)
* ``junction`` — Windows directory junction via ``mklink /J``
* ``copy``     — full directory copy

In ``symlink``/``junction`` modes, package upgrades are picked up by the host
immediately (next session). In ``copy`` mode the user must rerun
``cheneypowers install`` after every upgrade.
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
from typing import Callable, Iterable, Literal, Optional

from . import payload_dir

# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_TARGET_OCCUPIED = 2
EXIT_UNSUPPORTED_MODE = 3

DeployMode = Literal["symlink", "junction", "copy", "auto"]
ResolvedMode = Literal["symlink", "junction", "copy"]
TargetName = Literal["claude", "codex", "catpaw"]
ALL_TARGETS: tuple[TargetName, ...] = ("claude", "codex", "catpaw")

DEFAULT_PLUGIN_NAME = "cheneypowers"
CATPAW_SKILL_PREFIX = "cheneypowers-"
CODEX_MARKETPLACE_NAME = "cheneypowers-local"

# Codex `[plugins."<name>@<marketplace>"]` key once registered in config.toml.
CODEX_PLUGIN_KEY = f'plugins."{DEFAULT_PLUGIN_NAME}@{CODEX_MARKETPLACE_NAME}"'


# ---------------------------------------------------------------------------
# Errors / result type
# ---------------------------------------------------------------------------


class InstallError(RuntimeError):
    """An installer error with an associated CLI exit code."""

    def __init__(self, message: str, exit_code: int = EXIT_GENERIC) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class InstallResult:
    target_name: TargetName
    target_path: Path
    mode: ResolvedMode
    payload: Path
    backed_up_to: Optional[Path] = None
    extra: Optional[str] = None  # human-readable post-install note


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------


def is_windows() -> bool:
    return platform.system() == "Windows"


def _readlink(path: Path) -> Optional[Path]:
    try:
        if path.is_symlink():
            return Path(os.readlink(path))
    except OSError:
        pass
    return None


def _is_junction(path: Path) -> bool:
    if not is_windows():
        return False
    try:
        if not path.is_dir():
            return False
        return Path(os.path.realpath(path)) != path.resolve(strict=False)
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------


def _resolve_mode(requested: DeployMode) -> ResolvedMode:
    if requested != "auto":
        return _validate_mode(requested)
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
# Filesystem primitives — the only place we touch real disk
# ---------------------------------------------------------------------------


def _ensure_parent(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)


def _remove_existing(target: Path) -> None:
    """Remove anything at ``target`` that we own (symlink / dir / file)."""
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


def _link_one(src: Path, dest: Path, mode: ResolvedMode) -> None:
    """Place ``src`` at ``dest`` according to ``mode``.

    The caller is responsible for ensuring ``dest`` does not already exist.
    """
    if mode == "symlink":
        os.symlink(str(src), str(dest), target_is_directory=src.is_dir())
        return
    if mode == "junction":
        if not is_windows():
            raise InstallError(
                "Directory junctions are a Windows-only feature.",
                EXIT_UNSUPPORTED_MODE,
            )
        cmd = f'mklink /J "{dest}" "{src}"'
        completed = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if completed.returncode != 0:
            raise InstallError(
                "mklink /J failed: "
                + (completed.stderr.strip() or completed.stdout.strip() or "unknown error"),
                EXIT_GENERIC,
            )
        return
    # copy
    if src.is_dir():
        shutil.copytree(str(src), str(dest))
    else:
        shutil.copy2(str(src), str(dest))


# ---------------------------------------------------------------------------
# Target adapters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TargetAdapter:
    name: TargetName
    target_path: Path
    # entries inside the source repo to deploy, plus their dest names
    # (relative to target_path). For Claude/Codex this is a fixed set; for
    # CatPaw it is computed dynamically from skills/.
    entries_fn: Callable[[Path], list[tuple[Path, str]]]
    # marker file inside the target whose existence/format identifies a
    # managed deployment.
    marker_relpath: str
    # human-friendly post-install note.
    note: str = ""
    # called after deploy + after uninstall (for config.toml etc.)
    post_install: Optional[Callable[[Path], None]] = None
    post_uninstall: Optional[Callable[[Path], None]] = None


# Default Claude/Codex payload entries (one symlink per top-level dir):
#  - .claude-plugin / .codex-plugin (the manifest)
#  - hooks (Claude Code & Codex share the same hook protocol)
#  - skills (the actual content)
#  - assets (icons)
_CLAUDE_ENTRIES = (".claude-plugin", "hooks", "skills", "assets")
_CODEX_ENTRIES = (".codex-plugin", "hooks", "skills", "assets")


def _claude_entries(payload: Path) -> list[tuple[Path, str]]:
    """Return [(src, dest_name), ...] for Claude Code."""
    return [
        (payload / name, name)
        for name in _CLAUDE_ENTRIES
        if (payload / name).exists()
    ]


def _codex_entries(payload: Path) -> list[tuple[Path, str]]:
    """Return [(src, dest_name), ...] for Codex."""
    return [
        (payload / name, name)
        for name in _CODEX_ENTRIES
        if (payload / name).exists()
    ]


def _catpaw_entries(payload: Path) -> list[tuple[Path, str]]:
    """Return [(src, dest_name), ...] for CatPaw.

    Each skill becomes its own ``cheneypowers-<skill-name>`` symlink directly
    under ``~/.catpaw/skills/``. CatPaw has no plugin/hooks integration so we
    only deploy skill folders.
    """
    skills_dir = payload / "skills"
    if not skills_dir.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "SKILL.md").is_file():
            continue
        out.append((child, f"{CATPAW_SKILL_PREFIX}{child.name}"))
    return out


def _claude_target_dir() -> Path:
    return Path.home() / ".claude" / "plugins" / DEFAULT_PLUGIN_NAME


def _codex_target_dir() -> Path:
    return Path.home() / ".codex" / "plugins" / DEFAULT_PLUGIN_NAME


def _catpaw_target_dir() -> Path:
    return Path.home() / ".catpaw" / "skills"


def _adapter_for(target: TargetName) -> _TargetAdapter:
    if target == "claude":
        return _TargetAdapter(
            name="claude",
            target_path=_claude_target_dir(),
            entries_fn=_claude_entries,
            marker_relpath=".claude-plugin/plugin.json",
            note="Open a new Claude Code session to load the plugin.",
        )
    if target == "codex":
        return _TargetAdapter(
            name="codex",
            target_path=_codex_target_dir(),
            entries_fn=_codex_entries,
            marker_relpath=".codex-plugin/plugin.json",
            note=(
                "Codex registered. Open a new Codex session to load the plugin."
            ),
            post_install=_codex_register_in_config,
            post_uninstall=_codex_unregister_from_config,
        )
    if target == "catpaw":
        return _TargetAdapter(
            name="catpaw",
            target_path=_catpaw_target_dir(),
            entries_fn=_catpaw_entries,
            # we use the first cheneypowers- entry as the marker
            marker_relpath=f"{CATPAW_SKILL_PREFIX}using-superpowers/SKILL.md",
            note=(
                "CatPaw / CatDesk: skills installed under ~/.catpaw/skills/cheneypowers-*. "
                "Auto-trigger is not supported on CatPaw; invoke skills explicitly."
            ),
        )
    raise InstallError(f"Unknown target: {target}", EXIT_GENERIC)


# ---------------------------------------------------------------------------
# Inspection (per-target)
# ---------------------------------------------------------------------------


def _detect_mode_at(probe: Path) -> Optional[ResolvedMode]:
    """How was ``probe`` deployed (symlink / junction / copy)?"""
    if not probe.exists() and not probe.is_symlink():
        return None
    if probe.is_symlink():
        return "symlink"
    if _is_junction(probe):
        return "junction"
    if probe.is_dir() or probe.is_file():
        return "copy"
    return None


def _claude_managed_entries(target: Path) -> list[Path]:
    """For Claude/Codex: list the four payload entries currently inside target."""
    if not target.is_dir():
        return []
    return [target / name for name in _CLAUDE_ENTRIES if (target / name).exists() or (target / name).is_symlink()]


def _catpaw_managed_entries(target: Path) -> list[Path]:
    """For CatPaw: list all ~/.catpaw/skills/cheneypowers-* entries."""
    if not target.is_dir():
        return []
    return sorted(
        p for p in target.iterdir() if p.name.startswith(CATPAW_SKILL_PREFIX)
    )


def _is_managed(adapter: _TargetAdapter) -> bool:
    """Heuristic: did *we* create something at ``adapter.target_path``?

    Claude/Codex: marker file ``<target>/.{claude,codex}-plugin/plugin.json``
    contains ``"name": "cheneypowers"``.
    CatPaw: at least one ``cheneypowers-*`` skill directory exists under
    ``~/.catpaw/skills/`` and has a SKILL.md inside.
    """
    if adapter.name == "catpaw":
        return any(
            (entry / "SKILL.md").exists() or (entry / "SKILL.md").is_symlink()
            for entry in _catpaw_managed_entries(adapter.target_path)
        )

    marker = adapter.target_path / adapter.marker_relpath
    if not marker.is_file():
        return False
    try:
        import json

        data = json.loads(marker.read_text(encoding="utf-8"))
        return data.get("name") == DEFAULT_PLUGIN_NAME
    except (OSError, ValueError):
        return False


def _detect_mode(adapter: _TargetAdapter) -> Optional[ResolvedMode]:
    if adapter.name == "catpaw":
        entries = _catpaw_managed_entries(adapter.target_path)
        if not entries:
            return None
        return _detect_mode_at(entries[0])
    probe = adapter.target_path / adapter.marker_relpath.split("/")[0]
    return _detect_mode_at(probe)


def _link_health(adapter: _TargetAdapter) -> str:
    """healthy / broken / missing for this adapter."""
    if adapter.name == "catpaw":
        entries = _catpaw_managed_entries(adapter.target_path)
        if not entries:
            return "missing"
        # if any entry is a broken symlink, mark broken; otherwise healthy
        for entry in entries:
            if entry.is_symlink():
                try:
                    entry.resolve(strict=True)
                except (OSError, RuntimeError):
                    return "broken"
            elif not entry.exists():
                return "broken"
        return "healthy"

    probe = adapter.target_path / adapter.marker_relpath.split("/")[0]
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
# Codex config.toml registration
# ---------------------------------------------------------------------------


def _codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _codex_register_in_config(payload: Path) -> None:
    """Register CheneyPowers in ``~/.codex/config.toml``.

    We need to add (or update):
      [marketplaces.cheneypowers-local]
      source_type = "local"
      source = "<absolute path to repo root>"

      [plugins."cheneypowers@cheneypowers-local"]
      enabled = true

    Done with simple line-based edits to keep the existing file's comments
    and other entries intact.
    """
    cfg = _codex_config_path()
    if not cfg.parent.is_dir():
        cfg.parent.mkdir(parents=True, exist_ok=True)
    text = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""

    payload_str = str(payload.resolve())
    marketplace_block = (
        f"[marketplaces.{CODEX_MARKETPLACE_NAME}]\n"
        f'source_type = "local"\n'
        f'source = "{payload_str}"\n'
    )
    plugin_block = (
        f"[{CODEX_PLUGIN_KEY}]\n"
        f"enabled = true\n"
    )

    # Ensure existing content ends with a blank line before we append.
    if text and not text.endswith("\n\n"):
        text = text.rstrip("\n") + "\n\n"

    text = _toml_upsert_block(
        text,
        section_header=f"[marketplaces.{CODEX_MARKETPLACE_NAME}]",
        new_block=marketplace_block.lstrip(),
    )
    # Blank line between the two appended sections for readability.
    if not text.endswith("\n\n"):
        text = text.rstrip("\n") + "\n\n"
    text = _toml_upsert_block(
        text,
        section_header=f"[{CODEX_PLUGIN_KEY}]",
        new_block=plugin_block.lstrip(),
    )

    if not text.endswith("\n"):
        text += "\n"
    cfg.write_text(text, encoding="utf-8")


def _codex_unregister_from_config(payload: Path) -> None:
    """Remove the two blocks we added in ``_codex_register_in_config``."""
    cfg = _codex_config_path()
    if not cfg.is_file():
        return
    text = cfg.read_text(encoding="utf-8")
    text = _toml_remove_block(text, f"[marketplaces.{CODEX_MARKETPLACE_NAME}]")
    text = _toml_remove_block(text, f"[{CODEX_PLUGIN_KEY}]")
    cfg.write_text(text, encoding="utf-8")


def _toml_upsert_block(text: str, *, section_header: str, new_block: str) -> str:
    """Replace the TOML block starting with ``section_header`` (or append)."""
    lines = text.splitlines()
    start = _find_section_start(lines, section_header)
    if start is None:
        # append
        sep = "" if not text or text.endswith("\n") else "\n"
        if not new_block.startswith("\n"):
            new_block = "\n" + new_block
        return text + sep + new_block.lstrip("\n") + ("" if new_block.endswith("\n") else "\n")
    end = _find_section_end(lines, start + 1)
    return "\n".join(lines[:start]) + ("\n" if start > 0 else "") + new_block.rstrip("\n") + "\n" + "\n".join(lines[end:])


def _toml_remove_block(text: str, section_header: str) -> str:
    lines = text.splitlines()
    start = _find_section_start(lines, section_header)
    if start is None:
        return text
    end = _find_section_end(lines, start + 1)
    # also drop the trailing blank line if present
    while end < len(lines) and lines[end].strip() == "":
        end += 1
        break
    return "\n".join(lines[:start] + lines[end:]).rstrip() + "\n"


def _find_section_start(lines: list[str], header: str) -> Optional[int]:
    needle = header.strip()
    for i, line in enumerate(lines):
        if line.strip() == needle:
            return i
    return None


def _find_section_end(lines: list[str], from_index: int) -> int:
    for j in range(from_index, len(lines)):
        s = lines[j].strip()
        if s.startswith("[") and s.endswith("]"):
            return j
    return len(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def install(
    target_name: TargetName,
    *,
    mode: DeployMode = "auto",
    force: bool = False,
) -> InstallResult:
    """Deploy the plugin payload for one target.

    Parameters
    ----------
    target_name:
        ``"claude"``, ``"codex"`` or ``"catpaw"``.
    mode:
        ``symlink`` | ``junction`` | ``copy`` | ``auto``.
    force:
        For Claude/Codex: replace the target if it exists and isn't ours.
        For CatPaw: also overwrite individual ``cheneypowers-*`` skill
        directories that aren't symlinks pointing at our repo.
    """
    payload = payload_dir()
    adapter = _adapter_for(target_name)
    target = adapter.target_path

    backed_up: Optional[Path] = None

    if adapter.name == "catpaw":
        # ~/.catpaw/skills/ is a shared directory; we don't own it. We only
        # manage the cheneypowers-* entries inside it.
        target.mkdir(parents=True, exist_ok=True)
        _catpaw_clean_managed(target, force=force)
    else:
        _ensure_parent(target)
        if (target.exists() or target.is_symlink()) and _is_managed(adapter):
            _remove_existing(target)
        elif target.exists() or target.is_symlink():
            if not force:
                raise InstallError(
                    f"Target {target} already exists and is not a CheneyPowers "
                    "deployment. Pass --force to back it up and replace it.",
                    EXIT_TARGET_OCCUPIED,
                )
            backed_up = _backup_existing(target)
        target.mkdir(parents=True, exist_ok=False)

    resolved = _resolve_mode(mode)
    used = _attempt_deploy(adapter, payload, resolved, fallback=mode == "auto")

    if adapter.post_install is not None:
        try:
            adapter.post_install(payload)
        except Exception as exc:  # noqa: BLE001
            raise InstallError(
                f"Payload deployed, but post-install step failed: {exc}",
                EXIT_GENERIC,
            ) from exc

    return InstallResult(
        target_name=adapter.name,
        target_path=target,
        mode=used,
        payload=payload,
        backed_up_to=backed_up,
        extra=adapter.note,
    )


def _catpaw_clean_managed(skills_dir: Path, *, force: bool) -> None:
    """Remove any existing ``cheneypowers-*`` entries we previously installed.

    If ``force=False``, we only remove entries that are symlinks (assumed to
    be ours). If ``force=True``, we also remove plain dirs/files matching
    the prefix.
    """
    for entry in _catpaw_managed_entries(skills_dir):
        if entry.is_symlink():
            entry.unlink()
        elif force:
            _remove_existing(entry)
        else:
            raise InstallError(
                f"Refusing to overwrite non-symlink CatPaw skill: {entry}. "
                "Pass --force to delete and replace it.",
                EXIT_TARGET_OCCUPIED,
            )


def _attempt_deploy(
    adapter: _TargetAdapter,
    payload: Path,
    primary: ResolvedMode,
    *,
    fallback: bool,
) -> ResolvedMode:
    chain: Iterable[ResolvedMode]
    if fallback and primary == "symlink" and is_windows():
        chain = ("symlink", "junction", "copy")
    elif fallback and primary == "symlink":
        chain = ("symlink",)
    elif fallback and primary == "junction":
        chain = ("junction", "copy")
    else:
        chain = (primary,)

    last_error: Optional[BaseException] = None
    for candidate in chain:
        try:
            _deploy_with_mode(adapter, payload, candidate)
            return candidate
        except (OSError, InstallError) as exc:
            last_error = exc
            _undo_partial(adapter)
            continue

    if isinstance(last_error, InstallError):
        raise last_error
    raise InstallError(
        f"Could not deploy {adapter.name} via any of {list(chain)}: {last_error}",
        EXIT_GENERIC,
    )


def _deploy_with_mode(
    adapter: _TargetAdapter, payload: Path, mode: ResolvedMode
) -> None:
    entries = adapter.entries_fn(payload)
    if not entries:
        raise InstallError(
            f"No payload entries found for target '{adapter.name}'. "
            "Did the package get built correctly?",
            EXIT_GENERIC,
        )
    for src, dest_name in entries:
        dest = adapter.target_path / dest_name
        if dest.exists() or dest.is_symlink():
            _remove_existing(dest)
        _link_one(src, dest, mode)


def _undo_partial(adapter: _TargetAdapter) -> None:
    """Roll back a partial deploy attempt (best-effort)."""
    if adapter.name == "catpaw":
        for entry in _catpaw_managed_entries(adapter.target_path):
            try:
                _remove_existing(entry)
            except OSError:
                pass
        return
    if adapter.target_path.exists() or adapter.target_path.is_symlink():
        try:
            _remove_existing(adapter.target_path)
        except OSError:
            pass


def uninstall(target_name: TargetName, *, force: bool = False) -> bool:
    """Remove a previously-installed deployment for one target.

    Returns True if anything was removed.
    """
    payload = payload_dir()
    adapter = _adapter_for(target_name)
    removed_anything = False

    if adapter.name == "catpaw":
        for entry in _catpaw_managed_entries(adapter.target_path):
            if entry.is_symlink() or force:
                try:
                    _remove_existing(entry)
                    removed_anything = True
                except OSError:
                    pass
            else:
                raise InstallError(
                    f"Refusing to remove non-symlink CatPaw skill: {entry}. "
                    "Pass --force to delete it.",
                    EXIT_TARGET_OCCUPIED,
                )
    else:
        target = adapter.target_path
        if not target.exists() and not target.is_symlink():
            removed_anything = False
        else:
            if not _is_managed(adapter) and not target.is_symlink():
                if not force:
                    raise InstallError(
                        f"Refusing to remove {target}: it does not look like a "
                        "CheneyPowers deployment. Pass --force to delete anyway.",
                        EXIT_TARGET_OCCUPIED,
                    )
            _remove_existing(target)
            removed_anything = True

    if adapter.post_uninstall is not None:
        try:
            adapter.post_uninstall(payload)
        except Exception:  # noqa: BLE001
            # don't fail uninstall just because we couldn't tidy a config file
            pass

    return removed_anything


def status_one(target_name: TargetName) -> dict:
    payload = payload_dir()
    adapter = _adapter_for(target_name)
    return {
        "target_name": adapter.name,
        "target_path": adapter.target_path,
        "payload": payload,
        "mode": _detect_mode(adapter),
        "health": _link_health(adapter),
        "managed": _is_managed(adapter),
        "package_version": _package_version(),
    }


def status_all() -> list[dict]:
    return [status_one(t) for t in ALL_TARGETS]


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def _package_version() -> str:
    from . import __version__ as v

    return v


def python_version_str() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

