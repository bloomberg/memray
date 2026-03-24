# Spec: Vendor Textual into Memray

## Problem

Memray depends on Textual (`textual >= 0.41.0`) for two interactive reporters:
the TUI live reporter and the Tree reporter. Textual's frequent releases
(sometimes weekly) regularly break memray's test suite. We declare support for
`textual >= 0.43, != 0.65.2, != 0.66` in tests but don't test against all
supported versions in CI, so regressions against older Textual versions go
undetected.

Vendoring Textual lets us upgrade on our own schedule, eliminates version
compatibility concerns, and removes the `_textual_hacks.py` compatibility shim.

## Scope

- Vendor Textual (pure Python, no C extensions) into `src/memray/_vendor/textual/`
- Do NOT vendor Textual's dependencies (rich, markdown-it-py, platformdirs)
- Textual's transitive deps become memray's direct deps instead
- This spec does NOT cover concern #2 (cross-environment attach / lazy imports
  for tracking isolation) — that is a separate effort

## Current State

### Files using Textual (3 files, ~1,360 lines)
- `src/memray/reporters/tui.py` — TUI live reporter (6 custom classes)
- `src/memray/reporters/tree.py` — Tree reporter (4 custom classes)
- `src/memray/reporters/_textual_hacks.py` — Compat shim for version diffs

### Textual APIs used
- `textual.app.App`, `textual.screen.Screen`
- `textual.widget.Widget`, `textual.widgets.*` (DataTable, Tree, Footer, Label, Static, TextArea)
- `textual.containers.*` (Container, Grid, Horizontal, Vertical, HorizontalScroll)
- `textual.reactive.reactive`, `textual.message.Message`
- `textual.binding.Binding`, `textual.strip.Strip`, `textual.color.*`
- `textual.dom.DOMNode`, `textual.events`, `textual.log`, `textual.work`

### CSS files
- `src/memray/reporters/tui.css` (105 lines)
- `src/memray/reporters/tree.css` (30 lines)

### Tests
- `tests/unit/test_tui_reporter.py` (1,081 lines)
- `tests/unit/test_tree_reporter.py` (1,994 lines)
- Uses `pytest-textual-snapshot` for SVG snapshot testing

## Design Decisions

### 1. Vendored location
`src/memray/_vendor/textual/`

Included in sdist/wheel automatically since it's under the memray package.

### 2. Import style
**Direct vendored imports.** All memray code changes from:
```python
from textual.app import App
```
to:
```python
from memray._vendor.textual.app import App
```

No sys.modules tricks, no re-export shims. Explicit and grep-friendly.

### 3. Rich handling

Two options are presented. Either way, rich is NOT vendored for Textual's sake
alone — the question is whether memray itself benefits from vendoring rich.

#### Option A: Do NOT vendor rich (baseline)

Vendored Textual continues to `from rich import ...` using the system-installed
rich. Bump memray's rich minimum from `>= 11.2.0` to `>= 13.3.3` to match
what the vendored Textual version requires.

**Pros:**
- Simpler vendoring — only Textual to manage
- Rich has excellent backward compatibility track record
- Smaller vendor directory

**Cons:**
- Version coupling: if vendored Textual's rich usage drifts from what the
  system rich provides, we'd get runtime errors
- Bumping rich minimum to 13.3.3 may break users on older rich (though 13.3.3
  is from mid-2023, so this is unlikely in practice)

**Dependency result:**
```python
install_requires = [
    "rich >= 13.3.3",  # bumped from 11.2.0
    ...
]
```

#### Option B: Also vendor rich

Vendor rich alongside Textual under `src/memray/_vendor/rich/`. Both vendored
Textual AND memray's own reporter code import from `memray._vendor.rich`.

**What changes compared to Option A:**

1. **Import rewriting scope expands.** The vendoring script must rewrite:
   - Textual's `from rich...` → `from memray._vendor.rich...` (automatic via
     `vendoring` tool if rich is in `vendor.txt`)
   - memray's own rich imports in 7 files:
     - `reporters/tui.py` — `rich.text.Text`, `rich.style.Style`,
       `rich.segment.Segment`, `rich.markup.escape`
     - `reporters/tree.py` — `rich.text.Text`, `rich.style.Style`,
       `rich.markup.escape`
     - `reporters/summary.py` — `rich.table.Table`, `rich.table.Column`,
       `rich.markup.escape`
     - `reporters/stats.py` — `rich.print` (as `rprint`)
     - `commands/transform.py` — `rich.print` (as `rprint`)
     - `commands/common.py` — `rich.print` (as `pprint`)
     - `_ipython/flamegraph.py` — `rich.print`

2. **Vendor directory grows.** Rich is ~25k lines of Python. Combined with
   Textual's ~40k, the vendor directory would be ~65k lines.

3. **Rich is removed from install_requires entirely.** No version coupling.

4. **`SortableText` subclasses `rich.text.Text`.** After vendoring, it would
   subclass `memray._vendor.rich.text.Text`. This is internal to the TUI
   reporter and not part of the public API, so no compatibility concern.

5. **Patch files may be needed for rich too.** Rich uses
   `importlib.metadata.version("rich")` for its own version — same issue as
   Textual, same fix (hardcode `__version__`).

6. **`vendor.txt` adds rich:**
   ```
   textual==X.Y.Z
   rich==A.B.C
   ```

7. **Lint rule and import guard expand** to also block bare `import rich` /
   `from rich`.

**Pros:**
- Full isolation — no version coupling between memray's rich and system rich
- memray becomes installable without requiring any specific rich version on
  the system (rich drops from install_requires)
- Future-proofs against rich API changes
- Consistent approach — all TUI-related deps are vendored

**Cons:**
- Larger vendor directory (~65k lines vs ~40k)
- More files to rewrite (7 memray source files use rich directly)
- Rich upgrades become another thing to manage in the vendor update cycle
- Rich has been very stable — vendoring it solves a largely theoretical problem
- If user code in the same process uses rich (e.g. via IPython), there'd be
  two copies in memory (no functional issue, just waste)

**Dependency result:**
```python
install_requires = [
    "jinja2 >= 2.9",
    "markdown-it-py",
    "platformdirs",
    # rich and textual fully vendored — no longer declared
]
```

#### Recommendation

Start with **Option A** (vendor Textual only). Rich has never caused a breakage
for memray. If rich version coupling becomes a real problem after Textual is
vendored, Option B can be added incrementally — the vendoring infrastructure
supports adding packages to `vendor.txt` without structural changes.

### 4. Transitive dependencies
**Add as memray direct dependencies** (do not vendor):
- `markdown-it-py` — used by Textual's Markdown widget
- `platformdirs` — used by Textual's config directory

These are pure-Python, stable, and low-risk.

### 5. Version pinning and metadata
- Hardcode `__version__` in the vendored `textual/__init__.py` (patch applied
  by vendoring script)
- Pin the vendored Textual version in a config file (`vendor.cfg` or
  `[tool.vendoring]` in pyproject.toml)
- Pin the newest Textual release that still supports Python 3.7. Treat Python
  3.7 compatibility as a hard constraint for future vendor bumps unless memray
  itself raises its minimum supported Python version

### 6. _textual_hacks.py
**Eliminate.** Apply the compatibility fixes directly as patches to the vendored
Textual source. Since we control the exact version, the hacks module becomes
unnecessary. Remove `_textual_hacks.py` and update `tui.py`/`tree.py` to use
the vendored API directly without shims.

### 7. CSS files
- memray's own CSS (`tui.css`, `tree.css`) stays in `src/memray/reporters/`
- Textual's internal CSS/TCSS files stay in `src/memray/_vendor/textual/` —
  file structure preserved so `__file__`-relative lookups work

### 8. What to strip from vendored copy
Remove from the vendored Textual source:
- `tests/`
- `docs/`
- `examples/`
- Any other non-runtime files (CHANGELOG, CONTRIBUTING, etc.)

Keep all runtime code including unused widgets — avoids breaking internal
transitive imports within Textual.

Keep Textual's license file. Let the `vendoring` tool fetch and place it
alongside the vendored package in `src/memray/_vendor/textual/`.

### 9. Dependency declaration changes

Depends on rich handling option chosen (see section 3).

**Option A (vendor Textual only):**
```python
install_requires = [
    "jinja2 >= 2.9",
    "rich >= 13.3.3",       # bumped to match vendored Textual's requirement
    "markdown-it-py",       # Textual transitive dep, now direct
    "platformdirs",         # Textual transitive dep, now direct
]
```

**Option B (vendor Textual + rich):**
```python
install_requires = [
    "jinja2 >= 2.9",
    "markdown-it-py",       # Textual transitive dep, now direct
    "platformdirs",         # Textual transitive dep, now direct
]
```

In both cases: remove `textual` from test requirements. Keep
`pytest-textual-snapshot` pinned to a version compatible with the vendored
Textual.

Runtime dependency changes are independent from test-only dependencies. If
`pytest-textual-snapshot` still requires a non-vendored `textual` import path,
keep `textual` in test requirements until the plugin is patched, replaced, or
explicitly proven to work against the vendored copy.

## Vendoring Tooling

### Approach: `vendoring` tool + custom script

Use the [`vendoring`](https://github.com/pradyunsg/vendoring) tool (same one
pip uses) configured via `[tool.vendoring]` in `pyproject.toml`, supplemented
by a wrapper script.

### Config (`pyproject.toml`)
```toml
[tool.vendoring]
destination = "src/memray/_vendor/"
requirements = "vendor.txt"
namespace = "memray._vendor"
patches-dir = "tools/vendoring/patches"

[tool.vendoring.transformations]
drop = [
    "tests/",
    "docs/",
    "examples/",
    "*.md",
    "*.rst",
    "*.txt",
    "CHANGELOG*",
]
```

### Pin file (`vendor.txt`)
```
textual==X.Y.Z         # newest release still supporting Python 3.7
rich==A.B.C          # only if Option B (vendor rich)
```

### Patch files (`tools/vendoring/patches/`)
Formal `.patch` files applied after copying and import rewriting:
- `textual-version.patch` — hardcode `__version__`
- `textual-hacks.patch` — apply fixes from `_textual_hacks.py` directly into
  Textual source (namespace_bindings compat, footer redraw, etc.)
- Additional patches as needed for `importlib.resources` rewrites

### Script and Makefile
- `scripts/vendor_textual.py` — wrapper script that:
  1. Reads pinned version from `vendor.txt`
  2. Runs `vendoring sync`
  3. Applies patches from `tools/vendoring/patches/`
  4. Strips non-runtime files
  5. Rewrites `__version__`
- `Makefile` target: `make vendor-update` calls the script

### Upgrade process
1. Update version in `vendor.txt`
2. Run `make vendor-update`
3. Update `pytest-textual-snapshot` pin if needed
4. Build sdist and wheel (`python -m build`)
5. Install the built wheel in a clean env and smoke-test importing the vendored
   reporter modules
6. Run at least one CSS/snapshot test from the wheel install to verify runtime
   assets were packaged correctly
7. Regenerate snapshot SVGs (`pytest --snapshot-update`)
8. Review diff, run tests, commit

## Import Safety

### Lint rule
Add a ruff/flake8 rule (or pre-commit check) that **forbids bare `import
textual` or `from textual` imports** in all memray source files. Only
`from memray._vendor.textual` is allowed. If Option B (vendor rich) is chosen,
also forbid bare `import rich` / `from rich`.

Implementation: custom ruff rule or a simple grep-based pre-commit hook:
```bash
# .pre-commit-config.yaml (or script)
# Always:
! grep -rn "from textual\b\|import textual\b" src/memray/ \
  --include="*.py" \
  --exclude-dir="_vendor"
# Option B only:
! grep -rn "from rich\b\|import rich\b" src/memray/ \
  --include="*.py" \
  --exclude-dir="_vendor"
```

## Test Changes

### Snapshot testing
- Pin `pytest-textual-snapshot` to a version compatible with the vendored
  Textual version
- Update both together when upgrading vendored Textual
- Do not use `sys.modules` aliasing or an import hook to test rewrite
  completeness
- If the plugin still requires bare `textual` imports, keep `textual` as a
  test-only dependency or patch/replace the plugin separately

### Reporter tests
Update all `from textual...` imports in test files to use
`from memray._vendor.textual...`.

## Packaging

- Include the full vendored Textual tree in source distributions:
  `recursive-include src/memray/_vendor/textual *`
- Verify wheel contents match the sdist and include non-Python runtime assets
  such as CSS/TCSS files

## Mypy / Type Checking

- Add `_vendor/` to mypy's `exclude` list in `pyproject.toml`:
  ```toml
  [tool.mypy]
  exclude = "tests/integration/(native_extension|multithreaded_extension)/|_vendor/"
  ```
- Reporter code that imports from `memray._vendor.textual` will still be
  type-checked; mypy will follow the imports into the vendored source for type
  resolution

## Repository Hygiene

- Add `.gitattributes` entry:
  ```
  src/memray/_vendor/** linguist-generated=true
  ```
  This hides vendored code from GitHub language stats and collapses it in PR
  diffs by default.

## Investigation Results

### CSS path resolution — SAFE
Textual resolves CSS paths using `inspect.getfile(obj.__class__)` in
`textual/_path.py:_make_path_object_relative()`. This is namespace-agnostic —
it finds the actual file on disk regardless of the Python package hierarchy.
memray's `CSS_PATH = "tui.css"` will continue to work since the CSS file is
co-located with the reporter module (not the vendored Textual code).

### `importlib.resources` — NOT USED
Textual does NOT use `importlib.resources` or `pkg_resources` for asset
loading. No additional rewriting needed beyond Python imports.

### `importlib.metadata.version("textual")` — NEEDS PATCHING
Textual's `__init__.py` lazily calls `importlib.metadata.version("textual")`
(hardcoded string) to get its version. This will fail under vendored namespace.
Already addressed by the `__version__` patching decision — the vendoring patch
must hardcode the version string directly instead of calling
`importlib.metadata`.

### Widget DEFAULT_CSS — SAFE
Widget CSS is defined as inline `DEFAULT_CSS: ClassVar[str]` string literals.
Source location tracking uses `inspect.getfile()` — namespace-agnostic.

### Theme loading — SAFE
Themes are hardcoded as Python dataclass objects in `textual/theme.py`. No
external file loading.

## Open Items to Investigate Before Implementation

1. **CSS class name derivation**: Textual widgets compute a CSS type name
   from the class name (not the module path), so this is likely safe — but
   verify with a quick test of a vendored copy.

2. **`vendoring` tool suitability**: Evaluate whether the `vendoring` tool
   handles Textual's size and structure well. It was designed for pip's use
   case (many small packages). Run a proof-of-concept:
   ```bash
   pip install vendoring
   vendoring sync  # with config pointing at textual
   ```
   Verify import rewriting, patch application, and stripping work correctly.
