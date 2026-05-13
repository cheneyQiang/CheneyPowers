# CheneyPowers

CheneyPowers is a personal Claude Code plugin that gives the agent a complete software-development methodology — TDD, systematic debugging, design-first brainstorming, plan-driven execution, code review workflows — through a curated set of composable skills and a SessionStart hook that loads them automatically.

It is a personal fork of the upstream [Superpowers](https://github.com/obra/superpowers) project, narrowed to a single harness (Claude Code) and packaged for installation via Python.

## How It Works

When you open a Claude Code session, the SessionStart hook in this plugin reads `skills/using-superpowers/SKILL.md` and injects it as additional context. From that point on, the agent automatically reaches for the right skill at the right moment:

1. **brainstorming** — refines a rough idea into a design before any code is written.
2. **using-git-worktrees** — sets up an isolated branch + worktree once a design is approved.
3. **writing-plans** — breaks the design into bite-sized tasks with exact file paths and verification steps.
4. **subagent-driven-development** / **executing-plans** — dispatches the work, with two-stage review.
5. **test-driven-development** — enforces RED-GREEN-REFACTOR throughout implementation.
6. **requesting-code-review** — runs a structured review pass against the plan.
7. **finishing-a-development-branch** — verifies tests, decides merge / PR / discard, cleans up.

You don't need to invoke skills manually. They auto-trigger because the bootstrap is loaded at session start.

## Installation

CheneyPowers ships as a Python package and a Claude Code plugin in the same repo. Install the package with pip, then run one command — the `cheneypowers` CLI delegates to `claude plugin marketplace add` + `claude plugin install` under the hood, so the plugin is registered exactly the way Claude Code expects.

**Prerequisite:** the `claude` CLI must already be on your PATH. If it lives somewhere unusual, set `CHENEYPOWERS_CLAUDE_BIN=/absolute/path/to/claude`.

### From a local checkout (the path used in v0.x)

```bash
git clone <your-fork-url> cheneypowers
cd cheneypowers
pip install -e .
cheneypowers install
```

`cheneypowers install` runs:

1. `claude plugin marketplace add <payload-dir> --scope user` — registers this repo as a local marketplace named `cheneypowers-dev`.
2. `claude plugin install cheneypowers@cheneypowers-dev --scope user` — enables the plugin in user scope.

Restart Claude Code (or open a new session) and the plugin is active. Both Claude CLI calls are idempotent, so it is safe to rerun.

### From PyPI (when published)

```bash
pip install cheneypowers
cheneypowers install
```

> v0.1.0 is not yet published to PyPI. Use the local checkout flow above.

### Platform notes

Deployment is identical across macOS, Linux, and Windows because all the filesystem work is done by the `claude` CLI rather than by this installer. There are no symlink / junction / copy modes any more.

## CLI Reference

```text
cheneypowers install   [--source PATH] [--scope {user,project,local}] [--force]
cheneypowers uninstall [--force]
cheneypowers status    [--source PATH]
cheneypowers --version
```

- `--source PATH` — override the marketplace source. Defaults to the payload that ships with the installed package (i.e. the repo root for editable installs, `site-packages/cheneypowers/_payload` for wheels).
- `--scope` — forwarded to `claude plugin marketplace add` / `claude plugin install`. Defaults to `user`.
- `--force` on `install` — tear down any prior registration first, then re-add. Useful when developing the plugin.

`cheneypowers status` prints the package version, the marketplace source path, whether the marketplace is registered, and whether the plugin is enabled. If the `claude` CLI is missing, status still prints what it can and explains how to fix it.

## Updating

```bash
pip install --upgrade cheneypowers   # or `pip install -e .` after `git pull`
```

When you upgrade an editable install, Claude Code sees the new payload immediately on the next session — the marketplace source still points at your working tree. For a wheel-based install, the source points at `site-packages/cheneypowers/_payload/`, which pip overwrites on upgrade, so the next session also picks up the new content. You only need to rerun `cheneypowers install` if you change `--scope` or `--source`.

## Uninstalling

```bash
cheneypowers uninstall   # claude plugin uninstall + claude plugin marketplace remove
pip uninstall cheneypowers
```

Run `cheneypowers uninstall` *before* `pip uninstall`. After `pip uninstall`, the bundled payload path goes away and any leftover marketplace registration would point at a non-existent directory.

## What's Inside — Skills Library

**Testing**
- **test-driven-development** — RED-GREEN-REFACTOR cycle (with testing anti-patterns reference)

**Debugging**
- **systematic-debugging** — 4-phase root cause process (root-cause-tracing, defense-in-depth, condition-based-waiting)
- **verification-before-completion** — confirm it's actually fixed before declaring done

**Collaboration** 
- **brainstorming** — Socratic design refinement
- **writing-plans** — detailed implementation plans
- **executing-plans** — batch execution with checkpoints
- **dispatching-parallel-agents** — concurrent subagent workflows
- **requesting-code-review** / **receiving-code-review**
- **using-git-worktrees** / **finishing-a-development-branch**
- **subagent-driven-development** — fast iteration with two-stage review

**Meta**
- **writing-skills** — how to write new skills
- **using-superpowers** — the bootstrap that loads at session start

> Note on naming: skills are referenced internally as `superpowers:<name>` (e.g. `superpowers:brainstorming`). That namespace is preserved unchanged because skill files cross-reference each other by ID. The project / package / plugin brand is `CheneyPowers` / `cheneypowers`; the skill ID prefix is a separate, stable internal name.

## Philosophy

- **Test-Driven Development** — write tests first, always.
- **Systematic over ad-hoc** — process over guessing.
- **Complexity reduction** — simplicity as the primary goal.
- **Evidence over claims** — verify before declaring success.

## License

MIT — see `LICENSE`.

## Credits

Skills content and the SessionStart bootstrap pattern are adapted from [Superpowers](https://github.com/obra/superpowers) by Jesse Vincent. CheneyPowers narrows the scope to Claude Code and adds the Python-based installer; rebranding and packaging by CheneyQiang.
