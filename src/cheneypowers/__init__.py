"""CheneyPowers — personal skills library for Claude Code.

This package ships the Claude Code plugin payload (skills, hooks, manifests,
assets) and a small CLI (``cheneypowers``) that deploys the payload into the
user's ``~/.claude/plugins/`` directory.
"""

from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

__all__ = ["__version__", "payload_dir"]


def _read_version_from_plugin_json() -> str:
    """Fallback: read the version directly from the bundled plugin.json.

    Used when the package is run from a source checkout (``python -m
    cheneypowers``) before being installed, in which case
    ``importlib.metadata.version`` cannot find distribution metadata.
    """
    plugin_json = payload_dir() / ".claude-plugin" / "plugin.json"
    if plugin_json.is_file():
        try:
            return json.loads(plugin_json.read_text(encoding="utf-8"))["version"]
        except (OSError, ValueError, KeyError):
            pass
    return "0.0.0+unknown"


def _resolve_version() -> str:
    try:
        return metadata.version("cheneypowers")
    except metadata.PackageNotFoundError:
        return _read_version_from_plugin_json()


def payload_dir() -> Path:
    """Return the directory containing the plugin payload.

    Resolution order:

    1. ``<this package>/_payload`` — the canonical layout produced by the
       hatch wheel build.
    2. The repository root, when running from an editable install
       (``pip install -e .``) or directly from a source checkout. We detect
       this by walking up from the source file looking for ``.claude-plugin``.
    """
    here = Path(__file__).resolve().parent
    bundled = here / "_payload"
    if (bundled / ".claude-plugin").is_dir():
        return bundled

    # Editable install / source checkout: walk up to locate the repo root.
    for candidate in (here, *here.parents):
        if (candidate / ".claude-plugin").is_dir() and (candidate / "skills").is_dir():
            return candidate

    raise RuntimeError(
        "Could not locate the CheneyPowers plugin payload. Expected either "
        f"{bundled} (built wheel layout) or a repo root containing "
        ".claude-plugin/ and skills/ when running from source."
    )


__version__ = _resolve_version()

