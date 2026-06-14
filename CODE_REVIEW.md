# OBSCURA — Code Review

**Date:** 2026-06-10  ·  **Scope:** Python backend (≈3.8k LOC, 14 modules) + vanilla-JS frontend (script.js/index.html/styles.css)
**Reviewer focus (as requested):** SOLID, OOP structure, DSA, plus correctness / security / hygiene.

This document is the *findings* phase. Fixes are applied in subsequent, individually-committed
refactor phases (see `REFACTOR_SUMMARY.md` when complete). Each finding is tagged with a
severity and a concrete remedy.

Severity: 🔴 critical · 🟠 high · 🟡 medium · 🔵 low/nit

---

## 0. Overall assessment

OBSCURA is a **well-organized** project for its size: clear module boundaries, good docstrings,
sensible use of `ThreadPoolExecutor` for I/O fan-out, parameterized SQL, and a tidy per-engine
parser dispatch in `search.py`. It is *not* a rewrite candidate.

The highest-value improvements are **DRY/SOLID consolidation** of three kinds of duplicated
infrastructure (DB connections, Tor sessions, LLM-provider detection), removing a layer of
**import-time global state** that causes a real provider-key bug, splitting the **god-module
`app.py`**, and adding a **test safety net** (there are currently zero tests). Honest note on
DSA: the hot paths are dominated by network I/O, so there are only a handful of genuine
algorithmic wins — they're listed in §5 and I will *not* manufacture more.

---

## 1. Security 🔴🟠

| # | Sev | File:line | Finding | Fix |
|---|-----|-----------|---------|-----|
| S1 | 🔴 | `.env` (git history) | A real **OpenRouter key** (`sk-or-v1-…`) is committed in history and the repo has a GitHub remote (`DaniaFazal/OBSCURA-FYP`). The working-tree `.env` also holds a live key. | **Rotate the OpenRouter key now.** `.env` is now git-ignored & untracked (done in the first hygiene commit) so it won't be re-committed. History is *not* rewritten because the remote is shared — coordinate a `git filter-repo`/BFG scrub + force-push with the repo owner, or just rely on rotation. |
| S2 | 🟠 | `app.py:621` | `app.run(host="0.0.0.0", port=8501)` binds **all interfaces**. The app has **no authentication** and drives Tor crawling + LLM spend. On a shared/Kali network this is remotely reachable. | Default to `127.0.0.1`; make host/port env-configurable; document explicitly if LAN exposure is intended. |
| S3 | 🟡 | `app.py:206-226` | `/api/providers` POST writes attacker-supplied values into the on-disk `.env` and `os.environ`. Keys are allow-listed (good) but values are unvalidated and persisted. | Acceptable for a localhost single-user tool; once S2 is fixed the risk drops. Add light validation (no newlines, length cap) to avoid `.env` corruption. |
| S4 | 🔵 | `app.py:190` | `serve_static` does `Path(path).is_file()` then `send_from_directory(parent, path)`. `send_from_directory` is traversal-safe, but the `is_file()` check runs against the CWD and is misleading. | Rely on `send_from_directory`'s safe-join; drop the manual check or scope it. |

---

## 2. Correctness / bugs 🟠🟡

- **B1 🟠 — Saving a provider key at runtime may not take effect.** `app.py:112` `_reload_provider_modules()` calls `importlib.reload()` on `obscura_config`, `llm_utils`, `llm`. But `app.py` (and `llm.py`, `health.py`) bound names *by value* at import — e.g. `from llm import get_llm`, `from obscura_config import OPENAI_API_KEY`. After a reload those names still point at the **old** function/value objects, so a key added through the UI silently doesn't apply until full restart. **Root cause is the import-time-constant config pattern (see §3 DIP).** Fix: read config on demand via a config accessor; delete the reload hack.
- **B2 🔵 — `tor_utils.py` is entirely dead code.** `refresh_tor_circuit()` / `get_tor_exit_ip()` (the Tor "new identity" feature) are never imported anywhere. Either wire it into a `/api/tor/newnym` endpoint (it's genuinely useful for OSINT) or delete the module. *Recommend wiring it up* — it's good functionality.
- **B3 🔵 — Dead functions.** `seeds.py`: `mark_loaded`, `get_uncrawled`, `get_unloaded`, `seed_urls_from_sources` have 0 callers. `presets.py`: `get_preset_by_key` has 0 callers. Remove or cover with the feature that needs them.
- **B4 🔵 — Dead frontend constant.** `script.js` declares `API.config = "/api/config"` but there is **no such backend route** and nothing fetches it (the "config" button only opens a modal). Remove the key to avoid implying an endpoint exists.
- **B5 🔵 — Fragile re-export.** `health.py:8` imports `USER_AGENTS` *from `search`*, which itself imports it from `constants`. Import from `constants` directly.
- **B6 🔵 — Unhandled cast.** `app.py:528-531` `int(data.get("threads") or 4)` etc. raise `ValueError` → 500 if the client sends a non-numeric string, before the `try`. Coerce defensively.
- *(Verified NOT a bug: `health.py:60-66` — `start` is bound as the first statement inside `try`, so the `except` reference is safe. No change needed.)*

---

## 3. SOLID violations (the core of the refactor)

### Single Responsibility (SRP)
- **`app.py` (622 lines)** is a god-module: HTTP routing **+** `.env` file read/modify/write (`_upsert_env_file`) **+** provider-status formatting **+** the entire investigate orchestration pipeline (`generate()`), all in one file. → Split into `services/` (orchestration), an env-file manager, a provider service, and Flask **blueprints** per resource.
- **`obscura_config.py`** mixes *configuration* with *network discovery* — it opens sockets to probe Tor ports **at import time** (`:53-54`). Import-time side effects hurt testability and SRP. → Make probing lazy/cached behind a function or config object.
- **`health.py`** mixes provider-name derivation with health-checking (the provider naming is a copy of `llm.py`'s).

### Open/Closed (OCP)
- **Provider detection is duplicated `if/elif` string-matching on class names in three places** — `llm.py:106-116` (`_ensure_credentials`), `health.py:43-58` (provider label), and `app.py:36-43` (`PROVIDER_ENV_MAP`). Adding a provider means editing several branches in lockstep. → One **provider registry** (name, env var, class, credential requirement, label) that all three consume. Open for extension, closed for modification.

### Dependency Inversion (DIP)
- High-level modules depend on **concrete module-level constants** imported by value (`from obscura_config import OPENAI_API_KEY`). This is the tight coupling behind B1. → Depend on a small **config abstraction** (`config.openai_api_key` read on access, or a `Settings` object injected where needed).

### DRY (cross-cuts SRP)
- `_connect()` + identical PRAGMA setup is **copy-pasted in 3 files** (`investigations.py:48`, `seeds.py:38`, `presets.py:33`), as is `_row_to_dict`. → shared `db.py` connection helper / repository base.
- `get_tor_session()` exists **twice** (`scrape.py:65`, `search.py:64`) with near-identical `Retry`/`HTTPAdapter`/proxy setup; `crawler.py` imports `scrape`'s copy. → one Tor networking module.

---

## 4. OOP / structure

- **Persistence → Repository pattern.** Convert the three SQLite modules into repository classes over a shared `Database` (connection factory + schema init). Keeps parameterized SQL, removes duplication, makes the data layer mockable. Preserve the existing free-function API as thin shims so callers/tests don't break in one step.
- **Investigate pipeline → an orchestrator object** with discrete stages (refine → search → filter → scrape → summarize). Each stage is already a function; grouping them behind a `Pipeline` makes the SSE route in `app.py` a few lines and makes the pipeline unit-testable with fakes.
- **Search parsers** already use a `name → parser` dict (`search.py:234`) — a clean Strategy. Minor: formalize the parser signature and register via decorator so engines self-register (OCP).
- `BufferedStreamingHandler` (`llm_utils.py:20`) is reasonable as-is.

## 5. DSA — honest opportunities (limited; I/O-bound app)

- 🔵 **URL dedup normalization** (`search.py:336`): dedup key is `link.rstrip("/")`, so `http://x.onion` vs `https://x.onion/path` count as distinct. A normalized key (scheme-insensitive host + cleaned path) dedups better. Small correctness/quality win.
- 🔵 **`score_and_sort`** (`search.py:256`) is O(n·m) over query terms; fine for ≤ a few hundred results. Could hoist `terms` to a `set` and short-circuit, but impact is negligible. Leave unless profiling says otherwise.
- 🔵 **`get_all_tags`** rebuilds a set from comma-split strings each call — fine at current scale.
- The `_ENGINE_PARSERS` dict dispatch and the `seen`-set dedups are already the right data structures. **No hot path is algorithmically deficient** — the cost is Tor latency, so the real "performance" levers are concurrency (already present) and timeouts (already tuned). I am intentionally *not* adding tries/heaps/etc. where a list/dict/set is correct.

## 6. Lint / hygiene (ruff)

7× unused imports (`app.py:8 abort`, `crawler.py:26,34,194`, `health.py:5 requests`), 4× `E701`
multiple-statements-per-line (`export.py:142-156`), 1× `E402` mid-file import (`app.py:514
from flask import Response`), assorted `W293` trailing whitespace, missing trailing newlines,
implicit `Optional` typing (`investigations.py:130,161`). All auto-fixable or trivial.

## 7. Tests & tooling

- **Zero tests.** Added `pytest` + `ruff` to the venv and a characterization suite (Phase 2) covering
  pure logic (env cleaning, model resolution, search scoring/parsing/dedup, filter index parsing,
  markdown→PDF helpers, scrape truncation) — no network needed — so the refactor is verifiable.

## 8. Docs / packaging

- `README.md` "Project Structure" lists `bin/ lib/ plugins/ reports/ examples/ tests/` — **none exist**; the layout is flat. Rewrite to match reality.
- `requirements.txt` omits **`openai`** and **`anthropic`** though `llm.py` imports them directly
  (`import openai` is a hard top-level dep). They're only transitively present today. Add explicitly; consider pinning.
- `dockerignore` is **misnamed** — Docker only honors `.dockerignore`. Rename.
- No `.env.example`; onboarding relies on the real `.env`. Add a redacted template.

---

## Phase ordering (execution plan)

1. ✅ Safety net: `.gitignore`, untrack secrets/artifacts, baseline commits (done).
2. Characterization tests (lock behavior).
3. Persistence layer unification (DRY/DIP).
4. Tor/session unification + lazy config + kill the reload bug (DIP).
5. LLM provider registry (OCP/SRP).
6. `app.py` → services + blueprints (SRP).
7. Correctness bugs (B1–B6) + wire up Tor NEWNYM.
8. Frontend cleanup (conservative).
9. Hygiene & docs.
10. Verify (pytest/ruff/py_compile) + summary.

Every phase keeps public behavior identical (asserted by the Phase-2 tests) and is committed
separately so any step is independently revertable.
