# CheneyPowers — Project Notes

CheneyPowers is a personal Claude Code plugin packaged as a Python tool. It is a fork of the upstream Superpowers project, trimmed down to a single harness (Claude Code) and rebranded for personal use by CheneyQiang.

## Repository Layout

- `skills/` — the actual content. Each subdirectory is one skill, with `SKILL.md` as the entry point. **Do not rebrand `superpowers:` skill IDs** — they are the stable internal namespace used to cross-reference skills, not a project-level brand.
- `hooks/` — `session-start` is a bash script that emits Claude Code's `hookSpecificOutput.additionalContext` JSON, injecting the `using-superpowers` bootstrap into every new session. `run-hook.cmd` is a polyglot wrapper for Windows.
- `.claude-plugin/plugin.json` + `marketplace.json` — Claude Code plugin manifests (`name = cheneypowers`, `version = 0.1.0`, author `CheneyQiang`).
- `assets/` — plugin icon and SVG.
- `src/cheneypowers/` — Python installer package (added in M2). Provides the `cheneypowers` CLI which symlinks (or copies on Windows) the plugin payload into `~/.claude/plugins/cheneypowers/`.
- `pyproject.toml` — Python package metadata and CLI entry point.
- `tests/claude-code/`, `tests/skill-triggering/`, `tests/explicit-skill-requests/`, `tests/subagent-driven-dev/` — behavior tests inherited from upstream. Kept for reference; not all are wired into CI yet.
- `docs/` — historical design notes and plans inherited from upstream. Kept for context.
- `RELEASE-NOTES.md` — upstream history is preserved; CheneyPowers entries appear at the top.

## Working In This Repo

- One change per commit. Conventional commit style is fine but not required.
- When you modify a skill (`skills/*/SKILL.md`) you are changing agent behavior, not just prose. Expect to test before/after by opening a fresh Claude Code session.
- The acceptance test for the bootstrap: open a clean Claude Code session, send `Let's make a react todo list`, and confirm the `brainstorming` skill auto-triggers before any code is written. If it does not, the SessionStart hook is broken.
- Do not add third-party runtime dependencies to the Python installer without a clear reason. The whole point is "pip install + one command, done".

## What This Project Does NOT Try To Do

- Support multiple harnesses. v1 is Claude Code only. If you ever want Codex/Cursor/etc again, restore the corresponding `.codex-plugin/`, `.cursor-plugin/`, etc. from upstream history — but expect to maintain extra manifests.
- Track upstream Superpowers releases automatically. Pull the diff manually when you want something.
- Ship as a "marketplace" plugin via the official Anthropic plugin marketplace. Distribution is via PyPI / local `pip install`.

## Pointers

- Upstream Superpowers (for reference, not for PRs): https://github.com/obra/superpowers
- Claude Code plugin docs: https://docs.anthropic.com/en/docs/claude-code/plugins
