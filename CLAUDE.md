# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repository Is

MoviePilot-Plugins is the official plugin repository for MoviePilot—a media automation platform. This repo contains plugin source code, market index files, icons, tests, and documentation. It is **not** a standalone runtime; plugins run inside the MoviePilot host process (`jxxghp/MoviePilot`), sharing its Python environment and dependencies.

The host handles plugin loading, event dispatch, API, services, data, workflows, and Agent runtime. The frontend repo (`MoviePilot-Frontend`) handles config pages, dashboard, and Vue federated components.

## Directory Layout

Three plugin generations coexist; **V3 is the current development target**:

- `plugins.v3/` — New V3-only plugins (use this for all new plugins)
- `plugins.v2/` — Historical V2-only implementations
- `plugins/` — Even older or cross-version legacy implementations
- `package.v3.json`, `package.v2.json`, `package.json` — Market index files for each generation
- `tests/v3/`, `tests/v2/`, `tests/v1/` — Plugin tests (one subdirectory per plugin ID)
- `tests/ci/` — Repository tooling and CI gate tests
- `docs/` — Development guides, migration docs, FAQ
- `icons/` — Plugin icons
- `scripts/` — CI helper scripts

## Plugin Structure (V3)

```
plugins.v3/<plugin_id_lowercase>/
    __init__.py          # Main class lives here
    pyproject.toml       # Optional: extra Python dependencies
    README.md            # Recommended
    models.py            # Optional: data models
```

Naming rules:
- Plugin directory name = plugin main class name in lowercase (e.g., class `BrushFlow` → `plugins.v3/brushflow/`)
- Main class must be defined in `__init__.py` and extend `_PluginBase`
- Market index key in `package.v3.json` uses the class name (e.g., `"BrushFlow"`)

## Commands

### Run all tests (CI entry point — runs ci, v3, v2 generations in separate subprocesses)

```bash
<MoviePilot-backend-venv>/bin/python tests/run.py
```

### Run tests for a single generation

```bash
<MoviePilot-backend-venv>/bin/python -m pytest tests/v3
<MoviePilot-backend-venv>/bin/python -m pytest tests/v2
```

### Run tests for a single plugin

```bash
<MoviePilot-backend-venv>/bin/python -m pytest tests/v3/<plugin_id>
```

### Check V3 dependency install across platforms

```bash
uv run --no-project --python 3.14 python scripts/check_v3_dependency_install.py --python 3.14 --platform linux-x64
```

### Syntax compile check (fast, no runtime)

```bash
python -m py_compile plugins.v3/<plugin_id>/__init__.py
```

Tests require the MoviePilot backend to be present at `../MoviePilot` relative to this repo (or set `MOVIEPILOT_BACKEND_PATH`). Use the backend's venv interpreter, not a separate environment.

## Test Conventions

- Tests go in `tests/v3/<plugin_id>/test_*.py`, **never inside the plugin source directory** (plugins are copied whole during market sync; test files would be distributed to users)
- Import plugins via production namespace: `from app.plugins.<plugin_id> import <ClassName>`
- Use pytest style (functions or classes, `assert` statements); do not add `unittest.TestCase` or `unittest.main()`
- Prefer `object.__new__(<ClassName>)` to bypass `__init__` and test pure logic without the full runtime
- New V3 plugins **must** include corresponding tests; the CI enforces this

## Key Rules for Plugin Development

- Use `app.sdk` stable imports (`app.sdk.config`, `app.sdk.media`, `app.sdk.events`, `app.sdk.logging`, `app.sdk.network`, `app.sdk.services`, `app.sdk.utilities`) rather than reaching into host internals
- Access host data through `Oper`, `Chain`, or stable SDK; do not directly manipulate host Models or hold raw `SessionFactory`
- Database transaction decorators are only for plugin-owned tables
- `plugin_version`, the index `version`, and the latest `history` entry must all match
- Version history entries are listed newest-first, in semantic version descending order
- Plugin runtime data goes into the plugin data directory, not the source directory
- V3 extra dependencies go in the plugin's `pyproject.toml` `[project].dependencies`; do not commit plugin-level lock files
- Third-party dependencies install in the host shared environment; they must not downgrade or override MoviePilot core dependencies
- Before committing: run Python compile, version gate checks, relevant tests, and `git diff --check`

## CI Gates (PR to main)

- **Plugin version gate**: verifies version consistency across `package.json`, `package.v2.json`, `package.v3.json`
- **New plugin test gate**: new `plugins.v3/` directories must have matching `tests/v3/<id>/`
- **Federation CSS gate**: checks federated component CSS
- **Plugin test gate**: full test suite via `tests/run.py` against MoviePilot V3 backend
- **Dependency install gate**: installs V3 plugin dependencies in isolated environments across Linux x64, Linux arm64, Windows x64, macOS Intel, macOS ARM

## Documentation

- `docs/Plugin_Development.md` — **Primary guide** for new V3 plugin development
- `docs/V3_Plugin_Adaptation.md` — Migrating V2 plugins to V3
- `docs/V3_API_Response_Adaptation.md` — Backend API, Vue federated components
- `docs/Repository_Guide.md` — Index files, versioning, CI, releases
- `docs/FAQ.md` — Common issues by scenario
- `docs/V2_Plugin_Development.md` — Historical V2 reference only
- `tests/README.md` — Test infrastructure details
