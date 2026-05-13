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

CheneyPowers ships as a Python package. Install the package with pip, then run one command to drop the plugin into your Claude Code plugins directory.

### From a local checkout (the path used in v1)

```bash
git clone <your-fork-url> cheneypowers
cd cheneypowers
pip install -e .
cheneypowers install
```

`cheneypowers install` creates a symlink at `~/.claude/plugins/cheneypowers` pointing at the plugin payload inside the installed package. Restart Claude Code (or open a new session) and the plugin is active.

### From PyPI (when published)

```bash
pip install cheneypowers
cheneypowers install
```

> v0.1.0 is not yet published to PyPI. Use the local checkout flow above.

### Platform notes

| Platform | Default deploy mode | Fallback |
|----------|--------------------|----------|
| macOS / Linux | `os.symlink` | error out with a helpful message |
| Windows (Developer Mode on, or admin) | `os.symlink` | directory junction → copy |
| Windows (no privileges) | directory junction (`mklink /J`) | copy |

When the deploy mode is `copy`, you must rerun `cheneypowers install` after every `pip install --upgrade`.

## CLI Reference

```text
cheneypowers install   [--force] [--mode {symlink,junction,copy}] [--target PATH]
cheneypowers uninstall [--target PATH]
cheneypowers status
cheneypowers --version
```

`cheneypowers status` prints the package version, the payload directory inside `site-packages`, the install target under `~/.claude/plugins/`, the deploy mode in use, and whether the link is healthy.

## Updating

```bash
pip install --upgrade cheneypowers   # or `pip install -e .` after `git pull`
```

If the deploy mode is `symlink` or `junction`, the upgrade is picked up the next time Claude Code opens a session — no need to rerun `install`. If the deploy mode is `copy`, run `cheneypowers install` again to refresh the payload.

## Uninstalling

```bash
cheneypowers uninstall   # removes ~/.claude/plugins/cheneypowers
pip uninstall cheneypowers
```

Always run `cheneypowers uninstall` *before* `pip uninstall`, otherwise you may leave a dangling symlink that Claude Code will complain about.

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
