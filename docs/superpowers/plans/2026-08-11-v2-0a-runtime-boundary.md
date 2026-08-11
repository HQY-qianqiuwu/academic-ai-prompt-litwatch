# V2.0A Runtime Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the v1.7 contract and expose a validated Python-native runtime boundary without removing legacy assets.

**Architecture:** `Settings` owns a strict runtime mode. `RuntimeStatus` describes core dependencies without probing Dify. FastAPI exposes this state while existing search/Radar/subscription behavior remains unchanged.

**Tech Stack:** Python 3.11, Pydantic Settings, FastAPI, pytest.

## Global Constraints

- Base commit is annotated tag `dify-v1.7` at `dda17741bc2e8ffa872eb383752ec6786a00b6d0`.
- Python is authoritative; historical Dify DSL is frozen.
- Do not use `git add .`, destructive Git commands, force push, or create `litwatch-v2.0`.
- Every behavior change follows RED -> GREEN -> REFACTOR.

---

### Task 1: Frozen dependency audit and runtime mode

**Files:**
- Create: `docs/V2_0_RUNTIME_DEPENDENCY_AUDIT.md`
- Create: `src/litwatch/runtime.py`
- Modify: `src/litwatch/config.py`
- Modify: `.env.example`
- Test: `tests/test_runtime.py`

**Interfaces:**
- Produces: `RuntimeMode(str, Enum)` values `legacy`, `dual`, `python_default`, `dify_free`.
- Produces: `Settings.runtime_mode: RuntimeMode`, default `python_default`.
- Produces: `RuntimeStatus(mode, python_primary, requires_dify, requires_docker, requires_ssrf_proxy)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_runtime_defaults_to_python():
    settings = Settings(_env_file=None)
    assert settings.runtime_mode is RuntimeMode.PYTHON_DEFAULT
    assert RuntimeStatus.from_mode(settings.runtime_mode).requires_dify is False

def test_unknown_runtime_mode_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, runtime_mode="unknown")
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_runtime.py -q`
Expected: FAIL because `RuntimeMode` and `RuntimeStatus` do not exist.

- [ ] **Step 3: Implement the minimal enum/status/settings field and document every current Dify, Docker, SSRF, environment, lifecycle, Pipeline, and Analyzer dependency found in the v1.7 code.**

- [ ] **Step 4: Verify GREEN and regression**

Run: `python -m pytest tests/test_runtime.py tests/test_core.py -q`
Expected: PASS.

- [ ] **Step 5: Commit explicitly**

```powershell
git add docs/V2_0_RUNTIME_DEPENDENCY_AUDIT.md src/litwatch/runtime.py src/litwatch/config.py .env.example tests/test_runtime.py
git commit -m "feat(runtime): define Python-native runtime boundary"
```

### Task 2: Runtime status API and lifecycle ownership

**Files:**
- Modify: `src/litwatch/web.py`
- Modify: `src/litwatch/runtime.py`
- Test: `tests/test_runtime.py`

**Interfaces:**
- Produces: `GET /api/v2/runtime` returning only mode and boolean dependency flags.
- Produces: `ApplicationRuntime.start()` and `.stop()` idempotently owning scheduler lifecycle; later plans add migration and worker hooks through injected callables.

- [ ] **Step 1: Add failing tests that call start/stop twice and assert `GET /api/v2/runtime` reports Python primary with no Dify requirement.**
- [ ] **Step 2: Run `python -m pytest tests/test_runtime.py -q` and verify the route/lifecycle assertions fail for missing behavior.**
- [ ] **Step 3: Implement injected lifecycle hooks and move scheduler start/stop from the inline FastAPI lifespan into `ApplicationRuntime`.**
- [ ] **Step 4: Run `python -m pytest tests/test_runtime.py tests/test_scheduler.py tests/test_literature_search_api.py -q` and verify PASS.**
- [ ] **Step 5: Commit only `src/litwatch/runtime.py`, `src/litwatch/web.py`, and `tests/test_runtime.py` with `refactor(runtime): centralize application lifecycle`.**

