# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repository Is

MoviePilot-Plugins is the official plugin repository for MoviePilot (a media automation platform):
plugin sources, market index files, icons, tests, docs, and the release workflow. It is **not** a
standalone runtime — plugins load into the same Python process and shared dependency environment as
the MoviePilot host (`jxxghp/MoviePilot`, branch `v3`). The host owns plugin loading/lifecycle, event
dispatch, API/services/data, workflows, and the Agent runtime; `MoviePilot-Frontend` owns config
pages, dashboards, and Vue federated component rendering.

Because plugins share the host process, treat third-party dependencies, background threads, module
globals, and import-time side effects as process-wide concerns.

## Generations and Directory Layout

Three plugin generations coexist; **V3 is the only target for new work**:

- `plugins.v3/` — new V3-only plugins; index `package.v3.json`
- `plugins.v2/` — historical V2-only implementations; index `package.v2.json`
- `plugins/` — older/cross-version legacy; index `package.json`
- `tests/v1|v2|v3/<plugin_id>/` — tests, one subdirectory per plugin ID
- `tests/ci/` — repository tooling and CI gate tests (no backend runtime)
- `docs/`, `docs/faq/` — guides, migration docs, scenario FAQ
- `.github/scripts/`, `scripts/` — CI gate implementations

Naming/identity rules (all three must agree):

- Plugin main class `Foo` → directory `plugins.v3/foo/`, class defined in `__init__.py`
- Index key in `package.v3.json` is the **class name** (`Foo`), not the directory name
- `plugin_version` (in the class), the index `version`, and the newest `history` entry must match
- `history` is newest-first, semantic-version descending

Version numbering rule — **each numeric segment of `x.y.z` may only be a single digit 0-9**
(so the maximum is `9.9.9`). When a segment would reach 10, carry into the next segment instead:
`0.0.10` is forbidden, use `0.1.0`; `0.9.10` is forbidden, use `1.0.0`. This overrides the usual
semantic-versioning reading of those numbers (e.g. a carry out of patch does *not* mean a feature
release). Versions already published under the old scheme are left alone — the rule applies to
versions created from now on.

Alpha (pre-release) versions — the form is `x.y.z-alpha.n`, and **the same single-digit rule applies
to every segment of it, including `n`** (so `0.1.0-alpha.10` is forbidden, use `0.1.0-alpha.1` …
`0.1.0-alpha.9` then `0.2.0-alpha.0`).

**Before deploying, always ask the user whether this is an alpha version — do not infer it.** If it
is alpha: commit the code but do **not** build (`vite build` / `dist/`), do **not** deploy, and do
**not** dispatch the `Plugin Release` workflow.

**Decided policy (B): an alpha label never goes into a version field.** It is recorded only in commit
messages and docs — the three version fields (`plugin_version`, `package.json` `version`, index
`version` + newest `history` key) always stay a plain `x.y.z`. Per the user: "这类版本仅我们自己知道
就好，不破坏整个平台的规则."

Why this is a deliberate choice and not a limitation to work around: the version gate
(`.github/scripts/check_plugin_versions.py`) matches with `re.fullmatch(r"v?(\d+(?:\.\d+)*)")`, so any
`-alpha.n` suffix fails with "不是合法语义版本". That gate runs in `plugin-gate.yml`, `release.yml`
**and** the `.githooks/pre-push` hook, so an alpha string in a version field breaks pushes and CI.
Relaxing the gate was considered and explicitly declined — do **not** "fix" it to accept pre-release
suffixes, and do **not** work around it by inventing a separate alpha flag field.

## Commands

Tests need the MoviePilot backend. Default location is a sibling directory `../MoviePilot` (workspace
layout) or set `MOVIEPILOT_BACKEND_PATH`. Always use the backend's venv interpreter
(`../MoviePilot/.venv/bin/python`) — never a separate environment.

```bash
# Full regression: ci + v3 + compatible v2, each in its own subprocess (CI entry point)
../MoviePilot/.venv/bin/python tests/run.py

# One generation (never mix generations in one pytest process — same-named plugin packages collide)
../MoviePilot/.venv/bin/python -m pytest tests/v3
../MoviePilot/.venv/bin/python -m pytest tests/v2

# Single plugin, or a single test
../MoviePilot/.venv/bin/python -m pytest tests/v3/rsync115sync
../MoviePilot/.venv/bin/python -m pytest tests/v3/rsync115sync/test_plugin.py::test_name

# Fast syntax-only check (works without the backend, plain python3 is fine)
python3 -m py_compile plugins.v3/<plugin_id>/__init__.py
python3 -m compileall plugins.v3/<plugin_id>

# Version gate: index version vs plugin_version across all three indexes
python3 .github/scripts/check_plugin_versions.py package.json package.v2.json package.v3.json

# Federated component CSS gate (required after building Vue frontend artifacts)
python3 .github/scripts/check_federation_css.py

# New-plugin test gate: every new plugins.v3/ dir needs a tests/v3/<id>/ dir
python3 scripts/check_new_plugin_tests.py --base-ref origin/main

# V3 dependency install gate (per platform; manifest-declared platform subsets supported)
uv run --no-project --python 3.14 python scripts/check_v3_dependency_install.py --python 3.14 --platform linux-x64

# Vue federated frontend (inside a plugin that ships one)
yarn typecheck && yarn build     # build output goes to dist/assets/

git diff --check                 # whitespace check, part of the pre-commit routine
```

`.githooks/pre-push` runs the version gate and the federation CSS gate on every push. Enable it with
`git config core.hooksPath .githooks` if it is not already active.

Note: the backend may not exist locally. `py_compile`, the version gate, `check_federation_css.py`,
and the standalone scripts under `scripts/` and `.github/scripts/` run without it. Any pytest run
does not: `tests/conftest.py` imports `tests/_bootstrap.py`, which resolves the backend path at
import time and raises `RuntimeError` before collection — this applies to `tests/ci` too.

## Test Conventions

- Tests live at `tests/<gen>/<plugin_id>/test_*.py`, **never inside the plugin source directory** —
  market sync copies plugin directories wholesale (`shutil.copytree`), so bundled tests ship to users.
- Import plugins through the production namespace: `from app.plugins.<plugin_id> import <ClassName>`.
  Never add the plugin directory to `sys.path` or use a top-level package name; dual module identity
  duplicates event subscriptions, class state, and plugin instances.
- `tests/_bootstrap.py` is a thin shim that locates the backend and delegates to the host's
  `app.testing.bootstrap`; `tests/conftest.py` picks the generation from the pytest target paths and
  bootstraps the matching plugin directory. This is why generations cannot share one process, and why
  the backend must provide `app/testing/bootstrap`.
- pytest style only: functions or classes, `assert` statements. No `unittest.TestCase`,
  `unittest.main()`, or `if __name__ == "__main__"` entry points (`unittest.mock` is still fine).
- Prefer `object.__new__(<ClassName>)` to bypass `__init__` and test pure logic without the runtime.
- New V3 plugins must ship matching tests; CI enforces it.

## Plugin Architecture (V3)

Entry points on `_PluginBase` — the ones that matter most:

- Required lifecycle: `init_plugin(config)` (must be safely re-callable), `get_state()`,
  `get_api()`, `get_form()`, `get_page()`, `stop_service()`
- Optional: `get_command()` (remote commands), `get_service()` (scheduled/periodic jobs),
  `get_dashboard()` / `get_dashboard_meta()`, `get_render_mode()`, `get_sidebar_nav()`,
  `get_actions()` (workflow actions)
- `get_render_mode()` returns `("vuetify", None)` or `("vue", "dist/assets")`; Vue-mode plugins ship
  a module-federated build under `dist/assets/` (`remoteEntry.js` + `__federation_expose_*`) and keep
  their frontend sources (`src/`, `vite.config.js`, `package.json`, lockfile) in the plugin directory.
  The `../rsync115sync` plugin is the working reference for this layout.

Host access boundaries:

- Use stable SDK imports: `app.sdk.config`, `app.sdk.media`, `app.sdk.events`, `app.sdk.logging`,
  `app.sdk.network`, `app.sdk.services`, `app.sdk.utilities`.
- Host data goes through Oper / Chain / SDK. Do not import `app.db.models.*` host models, and do not
  import or hold `SessionFactory` / `AsyncSessionFactory` / `ScopedSession`.
- Choose storage by responsibility: `get_config()`/`update_config()` for user settings,
  `save_data()`/`get_data()`/`del_data()` for small serializable state, `get_data_path()` for files
  and large objects. Only build a plugin-owned table (SQLAlchemy 2.0 `Mapped`,
  `Base`, `db_query`/`db_update`, `ensure_table()` called from `init_plugin()`) when indexing or
  volume demands it. Transaction decorators are for plugin-owned tables only.
- Plugin runtime data goes to the plugin data directory, never back into the source directory.
- Async HTTP goes through `app.sdk.network.AsyncRequestUtils`, which uses HTTPX2 — catch
  `httpx2.RequestError`, not `httpx.RequestError`, and never call `httpx2.alias_httpx()`.
- V3 media identity is the pair `media_source` + `media_id`; do not rely on bare IDs.

Dependencies: V3 extra dependencies go in the plugin's `pyproject.toml`
(`[project].dependencies`, `dynamic = ["version"]`, real version stays in the plugin class). Do not
commit plugin-level lockfiles (`uv.lock`); V1/V2 keep `requirements.txt`. Dependencies install into
the host shared environment and must not downgrade or override MoviePilot core dependencies. Declare
a dependency-gate platform subset with:

```toml
[tool.moviepilot.dependency-gate]
platforms = ["linux-x64"]
```

Federated CSS is a hard constraint: never bundle global Vuetify/MDI styles into a remote component.
Share `vuetify` and `vuetify/styles` with `generate: false`, strip `node_modules/vuetify` and
`node_modules/@mdi` CSS in PostCSS, and never commit `__federation_shared_vuetify/styles-*.css` —
remote CSS lands in the host `document` and leaks into the whole UI. Run
`python .github/scripts/check_federation_css.py` after any frontend build.

## Index Files and Version Selection

MoviePilot resolves a plugin by generation: it checks the current generation's index first, then falls
back to non-excluded legacy entries. `"v3": false` on an entry blocks V3 fallback to that
implementation (set it when a V3-specific copy exists or the old contract is incompatible). `"v2":
true` in `package.json` marks a default entry usable under V2. `system_version` (pip-style range,
e.g. `">=3.0.0,<3"`) gates install/update/load against the host version — V3-specific implementations
declare `">=3.0.0"`.

When copying a V2 plugin into a V3-specific implementation, bump `x.y.z -> (x+1).0.0` (a generation
contract change is not a patch), add the `package.v3.json` entry, and set `"v3": false` on the old
entry.

## CI Gates (PR to main)

- Plugin version gate — index `version` vs class `plugin_version` (`check_plugin_versions.py`)
- New plugin test gate — new `plugins.v3/` dirs need `tests/v3/<id>/`
- Federation CSS gate
- Plugin test gate — `tests/run.py` against the MoviePilot V3 backend
- Dependency install gate — isolated install + `uv pip check` on Linux x64/arm64, Windows x64,
  macOS Intel/ARM (only runs when `plugins.v3/*/pyproject.toml` or the gate itself changes)

## Release

`.github/workflows/release.yml` triggers on any `package*.json` change. Only entries with
`"release": true` are packaged; the workflow maps each index to its directory
(`package.v3.json` → `plugins.v3/`). Tag format `PluginID_vVersion`, asset
`<plugin_dir_lower>_v<version>.zip`, skipped when the plugin directory is unchanged since the last
tag of the same plugin.

## Documentation

- `docs/Plugin_Development.md` — primary V3 plugin development guide (read first)
- `docs/V3_Plugin_Adaptation.md` — migrating V2 plugins to V3 (imports, media identity, transactions)
- `docs/V3_API_Response_Adaptation.md` — plugin API and host API response contract
- `docs/Repository_Guide.md` — indexes, versioning, CI, releases, repo boundaries
- `docs/FAQ.md` + `docs/faq/` — one doc per extension scenario (commands, services, dashboards, agents)
- `tests/README.md` — test infrastructure details
- `docs/Development_Log.md` — narrative log of significant plugin changes
