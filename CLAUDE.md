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

## Fork and Upstream Sync

This working copy is a **fork** of upstream `jxxghp/MoviePilot-Plugins` (`origin` = the personal
fork; `upstream` = jxxghp). `.github/workflows/sync-upstream.yml` merges `upstream/main` into `main`
on a daily schedule (and on `workflow_dispatch`): a clean merge auto-pushes to `main`; a conflicted
merge aborts, force-pushes a `sync-upstream` branch, and opens/refreshes a PR for manual resolution
(needs the `SYNC_TOKEN` secret — without it the run errors and prints a compare link instead).

Implications when editing:

- Upstream merges are performed by that workflow, not by hand. Keep fork-local changes tidy so they
  do not fight the merge. The workflow's own comment names `package.v2.json` and the `traktcleaner`
  plugin as frequent conflict points (files both sides have edited).
- **Fork-local plugins** exist that upstream does not have: V3 `Rsync115Sync` and `WatchSync` (plus a
  V2 `WatchSync`), as well as V3 `P115StrmHelper` (bundles offline cp314 wheels in `wheels/`). A second
  category is a **shared plugin the fork has diverged from**: `BrushFlow` exists upstream (v6.1.2) but
  this fork is far ahead (v6.4.13, ~18 fork-local commits). Develop them freely, but never assume upstream
  shares your state — an upstream merge will not supply the fork-only index entries, nor carry the fork's
  newer `BrushFlow` entry. Fork-local non-merge commits are dominated by `Rsync115Sync` (~135), then
  `BrushFlow` (~18), `WatchSync` (~15), and `P115StrmHelper`.
  Because `BrushFlow` and `P115StrmHelper` live in `package.v3.json`, upstream edits to the shared index
  files can conflict there too, not only in `package.v2.json`.
- `scripts/update_rsync115sync.sh` is a **gitignored** local helper (it embeds a personal NAS
  host/IP), and `.testhost/` is a gitignored partial stub — it has stub `app/` modules but **no**
  `app.testing`, so pytest cannot bootstrap against it. Neither is part of the repo.

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

A Vue-mode plugin has **two more** version fields, and they are checked far more weakly than the
three above: its own `package.json` `version` and the version chip hardcoded in `Config.vue`. Bump
all five. `check_plugin_versions.py` *does* inspect these two, but only as a **warning** by default —
at the time of writing four drift entries remain (`AgentResourceOfficer`, `FullScreenPosterWall`,
and `WatchSync` in both `package.v3.json` and `package.v2.json`; run the gate for the live list —
`BrushFlow` is aligned today but has drifted before). It becomes a hard **failure only for plugin IDs
in `CHECK_STRICT_PLUGINS`**, which `.githooks/pre-push` fills with the plugins your push touches.
Net effect: the hook is strictly stricter than the PR gate, so a drift you introduce in your own
plugin fails locally but would slip past CI — a false green (v0.2.2 shipped a fix for exactly this
drift).

Plugin source directories are copied wholesale into release zips — `release.yml` excludes only
`__pycache__` and `*.pyc` — so sibling modules, `dist/`, frontend sources, and any `*.md` inside
the plugin directory all ship to users. That is also why tests must live outside the plugin
directory, and why splitting a plugin into sibling modules needs no packaging change.

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

⚠️ **Exception — Vue-mode plugins (`get_render_mode()` returns `"vue"`).** For those, `dist/` *is*
the running code: the host loads the bundle, not the `.vue` sources. Skipping `vite build` does not
"hold back a release", it ships **stale UI that silently does not match the backend** — the user then
reports a bug against code that is not running. Build `dist/` for any change that touches `src/`,
alpha or not. (Verified on `Rsync115Sync`: a frontend fix without a rebuild left the old bundle on
the NAS and produced exactly that false report.) The "don't deploy" half of the rule still holds.

⚠️ **Caveat on "no version bump" (per-plugin, decided 2026-09-24).** If a plugin is deployed by
`git pull` into `local_plugins` rather than through the market, an un-bumped version is harmless:
the user gets the code on pull regardless. It is **not** harmless if the plugin is expected to update
via the market — the host's update check is `installed_version < index_version`
(`app/runtime/extensions/plugin/metadata.py`), so an unchanged version means **the market never
offers the update**. `Rsync115Sync` hit exactly this: alpha fixes shipped with no version change and
were unreachable. So "no version bump during alpha" is a decision that must be paired with
"deployed by pull", never made on its own.

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

> ⚠️ If neither the backend nor `pytest` is available (fresh clone, no sibling), the full suite
> **cannot** run. Do **not** report "all tests pass" in that state. Two honest options: build a
> throwaway stub host (a minimal `app/` with `_PluginBase`, `eventmanager`, `logger`, plus an
> `apscheduler` stand-in) and run the pure-logic cases through it, or state plainly that the suite
> was not run. When using a stub, always capture a **baseline** by stashing your changes and running
> the same selection against the original code — only the *delta* is meaningful, because a stub
> harness will always have some failures of its own (missing `fastapi`, `caplog` behaviour, private
> APIs). A prior session reported a fixed count of failing cases without a baseline; those failures
> turned out to be harness limitations, not regressions.

**Backend-free tests.** `tests/conftest.py` bootstraps the backend at import time, so *no* pytest run
works without it — not even `tests/ci`. But a test file that never imports `app.*` (e.g. one that
parses plugin sources with `ast`, or loads a backend-free sibling module through `importlib`) can
still run with **`--noconftest`**, which skips the bootstrap entirely. Use `uv` or any local python:

```bash
uv run --with pytest pytest tests/v3/<id>/test_x.py --noconftest -q
uv run --with pytest pytest tests/ci/test_v3_contract.py --noconftest -q
```

This is how pure-logic guards (template/source assertions, event-registration contracts, button
payload shape, CI gate contracts) stay runnable on a machine with no backend. It is not a substitute
for the full suite, and `tests/run.py` remains the CI entry point.

```bash
# Full regression: ci + v3 + compatible v2, each in its own subprocess (CI entry point)
../MoviePilot/.venv/bin/python tests/run.py

# One generation (never mix generations in one pytest process — same-named plugin packages collide)
../MoviePilot/.venv/bin/python -m pytest tests/v3
../MoviePilot/.venv/bin/python -m pytest tests/v2

# Single plugin, or a single test (backend environment)
../MoviePilot/.venv/bin/python -m pytest tests/v3/rsync115sync
../MoviePilot/.venv/bin/python -m pytest tests/v3/rsync115sync/test_plugin.py::test_name

# Fast syntax-only check (works without backend, plain python3 is fine)
python3 -m py_compile plugins.v3/<plugin_id>/__init__.py
python3 -m compileall plugins.v3/<plugin_id>

# Version gate: index version vs plugin_version across all three indexes
# (package.json / package.v2.json only fully check release:true entries;
#  package.v3.json checks every entry + V3 history/major-bump contract)
python3 .github/scripts/check_plugin_versions.py package.json package.v2.json package.v3.json

# Same gate in the strict form the pre-push hook uses: only the listed plugin IDs
# are checked for the package.json/Config.vue drift that is otherwise a warning.
CHECK_STRICT_PLUGINS=myplugin python3 .github/scripts/check_plugin_versions.py package.json package.v2.json package.v3.json

# Federated component CSS gate (required after building Vue frontend artifacts)
python3 .github/scripts/check_federation_css.py

# V3 import boundary gate: ast scan checking legacy compat imports & forbidden host access
# (requires backend at MOVIEPILOT_BACKEND_PATH or ../MoviePilot for app.runtime.compat.manifest)
python3 scripts/check_v3_imports.py
# Ratchet down import baseline after removing legacy imports/host db accesses:
python3 scripts/check_v3_imports.py --write-baseline

# New-plugin test gate: every new plugins.v3/ dir needs a tests/v3/<id>/ dir
python3 scripts/check_new_plugin_tests.py --base-ref origin/main

# V3 dependency install gate (per platform; manifest-declared platform subsets supported)
uv run --no-project --python 3.14 python scripts/check_v3_dependency_install.py --abi cp314 --platform linux-x64

# Vue federated frontend (inside a plugin that ships one) — run from the plugin directory.
# The build script is always `vite build`; pick the package manager from the lockfile that
# is present (pnpm-lock.yaml → pnpm, package-lock.json → npm, none → npm). No plugin here
# defines a typecheck script, and none use yarn. Build output must land in dist/assets/.
pnpm build    # when pnpm-lock.yaml exists (BrushFlow, Rsync115Sync)
npm ci && npm run build    # when package-lock.json exists (LunaTVSource, CourseOrganizer, …)

git diff --check                 # whitespace check; recommended before commit (no hook runs it)
```

`.githooks/pre-push` runs the version gate and the federation CSS gate on every push (it does not run
tests). Enable it with `git config core.hooksPath .githooks` if it is not already active — **check
this rather than assuming: in this working copy it is not set, so the hook does not run at all** and
the gates must be invoked by hand.

### Commit message convention

The fork is overwhelmingly Conventional Commits (`type(scope): subject`, ~90% of the last 300
non-merge commits). `scope` is the plugin ID lowercased (`brushflow`, `rsync115sync`); private
`alpha:` / `chore:` / `docs:` commits omit it. In the actively developed fork-local plugins
(`brushflow`, `rsync115sync`) the subject joins the *what* and the *why* with a full-width em dash:
`fix(brushflow): 站点刷流 v6.4.7 —— 复活区解析 H&R 标记`. Bodies are written in Chinese, start from
the observed symptom or wrong assumption, and state the consequence — not a restatement of the diff.
Do not add a separate "why" paragraph that merely repeats the subject.

Note: the backend may not exist locally. `py_compile`, the version gate, `check_federation_css.py`,
and the standalone scripts under `scripts/` and `.github/scripts/` run without it. Any pytest run
does not: `tests/conftest.py` imports `tests/_bootstrap.py`, which resolves the backend path at
import time and raises `RuntimeError` before collection — this applies to `tests/ci` too, even though
`tests/ci` never initializes the MoviePilot runtime (it only needs the backend on disk for bootstrap).

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
- New classes and methods need doc comments that state their responsibility (repo commit rule).

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
  `plugins.v3/rsync115sync` is the working reference for this layout.

### Event-handler and endpoint contracts (silent-failure traps)

These are host-side rules that cost a debugging session each when missed, because **every failure
mode here is silent**: no exception, no plugin log line, and the host still prints its own success
message. Source of truth is the host's `app/runtime/`, not this repo.

- **Register event handlers on the plugin class, never in a sibling Mixin.** The host resolves a
  handler's plugin instance by the **declaring class name**:
  `resolve_event_handler_instance(owner_class)` → `plugin_id = owner_class.__name__` → looks the
  plugin up in `_plugins`. A handler declared on `class FooOpsMixin` resolves to the string
  `"FooOpsMixin"`, which is not a plugin, so `invoke_sync` hits `if not resolved: return` and the
  handler is **dropped**. To split a plugin across files, the Mixin holds an ordinary method and the
  plugin class holds a thin decorated wrapper that calls it. Symptom: all remote commands seem to
  "execute" in the host log yet the plugin produces nothing.
- **Endpoint method signatures become FastAPI response models.** A method listed in `get_api()` is
  introspected by FastAPI; annotating a parameter with a host type such as `Event` fails
  (`Invalid args for response field`) and the **whole route silently fails to register** — the
  dashboard region that calls it just disappears. Use `Any` / plain types in endpoint signatures.
  (Internal methods are unaffected — only registered endpoints.)
- **Buttons: `callback_data` must be `[PLUGIN]<PluginID>|<content>`.** The host's callback router
  (`app/chain/message.py`) is an allowlist; bracket `[PLUGIN]` payloads are parsed by
  `application/messaging/plugin.py:parse_callback` and re-broadcast as `EventType.MessageAction`
  with `{plugin_id, text, userid, channel, …}`. Anything else (including a bare slash command) falls
  to a fallback that replies "回调数据格式错误" to the user — the plugin never sees the event. See
  `docs/faq/14-message-interaction.md`; a `MessageAction` handler needs an own-`plugin_id` guard
  because the event is shaped like a broadcast.
- **`callback_data` is capped at 64 bytes, and exceeding it fails the *entire* message**
  (`BUTTON_DATA_INVALID`) — not just that one button. Chinese text is 3 bytes per character, so a
  keyword-bearing payload blows the limit fast. Never put a filename/subject in `callback_data`;
  carry a short fingerprint and resolve it server-side, and drop buttons rather than lose the
  message.
- **`post_message` returns `None` and does not surface delivery failure.** `_messaging.py` logs the
  provider error and moves on, so a plugin cannot tell whether a notification arrived — and any
  "already notified" latch would then suppress retries, turning one failed send into permanent
  silence. Validate everything rejectable *before* sending.

### Host access boundaries

- Use stable SDK imports: `app.sdk.config`, `app.sdk.media`, `app.sdk.events`, `app.sdk.logging`,
  `app.sdk.network`, `app.sdk.services`, `app.sdk.utilities`.
- **Zero-tolerance import rules** (enforced by `scripts/check_v3_imports.py`, zero baseline allowed):
  - Never import or dynamically load other plugins (`app.plugins.<other>`).
  - Never modify `sys.path` (`sys.path.append(...)`, `sys.path.insert(...)`).
  - Never directly access host SQLite database files (`user.db`).
  - Never import from `app.sdk.legacy` / `app.sdk._legacy`.
- **Ratcheting legacy baseline** (`tests/ci/v3_import_baseline.json`):
  - Imports needing host compat manifest (`app.plugins._PluginBase`, `app.log`, `app.core.*`) and direct
    host data access (`app.db.models.*`, `SessionFactory`, `AsyncSessionFactory`, `ScopedSession`) are
    tracked in the baseline. New code must use `app.sdk` and Oper/Chain; baseline counts can only decrease.
    Run `python3 scripts/check_v3_imports.py --write-baseline` after cleaning up legacy imports.
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

### Dependencies & Manifest Contract

V3 extra dependencies go in `plugins.v3/<id>/pyproject.toml`. The manifest contract is enforced by
`tests/ci/test_v3_dependency_manifests.py`:
- `project.name = "moviepilot-plugin-<plugin_id_lower>"` (exact match required)
- `project.dynamic = ["version"]` — never commit a static `version` field (version stays in the plugin class)
- `project.requires-python = ">=3.14"` (aligned with V3 Python 3.14 host runtime)
- `project.dependencies` must be a static list of PEP 508 requirement strings
- Never commit plugin-level lockfiles (`uv.lock`) or `requirements.txt` under `plugins.v3/` (V1/V2 keep `requirements.txt`)
- Plugins must never execute package managers (`pip`, `uv`, etc.) via subprocess or shell
- Dependencies install into the host shared environment and must not downgrade or override MoviePilot core dependencies

Declare a dependency-gate platform subset with:

```toml
[tool.moviepilot.dependency-gate]
platforms = ["linux-x64"]
```

**Free-threaded (`v3t`) opt-out.** Besides the standard gate, CI runs a second dependency install
gate in a toolchain-less `python:3.14-slim` container against the **free-threaded** interpreter
(`--abi cp314t`, Linux x64/arm64 only). A dependency that has no `cp314t` wheel or pure-Python sdist
cannot install there. A plugin known to be incompatible declares it in the index, not in code:

```json
"AnimeUpscale": { "v3t": false }
```

Only a literal boolean `false` opts out — a missing field or any other value means "compatible".
The opt-out is read by `scripts/check_v3_dependency_install.py` (`FREE_THREADED_FIELD`), which
**errors if a manifest cannot be matched to exactly one `package.v3.json` ID** (case-folded
directory-name collisions, or a `pyproject.toml` with no index entry) rather than silently passing.
Current opt-outs: `AutoSubv2`, `AgentResourceOfficer`, `AnimeUpscale`.

Federated CSS is a hard constraint: never bundle global Vuetify/MDI styles into a remote component.
Remote CSS lands in the host `document` and leaks into the whole UI. Share `vue`/`vuetify` with
`generate: false` and strip `node_modules/vuetify` and `node_modules/@mdi` CSS in PostCSS. The gate
(`check_federation_css.py`) rejects a committed
`**/__federation_shared_vuetify/styles-*.css` and any CSS referenced by a `remoteEntry.js` that
contains unscoped global selectors (`html`, `body`, `:root`, `*`, `.v-*`, `.mdi-*`, `.rounded*`,
`.elevation-N`) — the historical fix for exactly that was commit `aa50460`. It also **requires every
federated plugin to be `"release": true`** in its index. Plugin configs differ on whether they list
`'vuetify/styles'` in `shared` (BrushFlow/WatchSync/Rsync115Sync omit it deliberately; CourseOrganizer/
LunaTVSource declare it) — both styles pass the gate. Run
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
entry. The version gate enforces this major jump for `package.v3.json` entries that still have a
legacy counterpart in `package.v2.json`/`package.json`, and also enforces that the newest `history`
key equals `version` and history is semver-descending.

## CI Gates (PR to main)

- Plugin version gate — index `version` vs class `plugin_version` (`check_plugin_versions.py`)
- New plugin test gate — new `plugins.v3/` dirs need `tests/v3/<id>/`
- Federation CSS gate — verify CSS scoping and no un-scoped global rules (`check_federation_css.py`)
- V3 import boundary gate — AST scan verifying zero-tolerance rules and baseline ratcheting (`scripts/check_v3_imports.py`, `test_v3_import_contract.py`)
- Plugin test gate — `tests/run.py` against the MoviePilot V3 backend
- Dependency install gate — isolated install + `uv pip check` on Linux x64/arm64, Windows x64,
  macOS Intel/ARM
- Dependency install gate, free-threaded (`cp314t`) — in a toolchain-less `python:3.14-slim`
  container on Linux x64/arm64; honours the `v3t` index opt-out (see above)

Both dependency gates only run when a `plugins.v3/*/pyproject.toml`, `package.v3.json`, the gate
script, its test, or `plugin-gate.yml` changes.

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
