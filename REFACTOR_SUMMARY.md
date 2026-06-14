# OBSCURA — Refactor Summary

**Date:** 2026-06-13  ·  Companion to `CODE_REVIEW.md` (the findings phase).

A code review + SOLID/OOP/DSA refactor of the backend, plus conservative frontend
and repo-hygiene fixes. Work was done in **behavior-preserving phases**, each
committed separately and guarded by a test suite, so any step is independently
revertable. **No code was pushed** (the repo shares a GitHub remote); all commits
are local.

---

## ⚠️ Action required (you)

1. **Rotate the OpenRouter API key.** A real `sk-or-v1-…` key exists in the
   **committed git history** of this repo, which has a GitHub remote
   (`DaniaFazal/OBSCURA-FYP`). It must be considered compromised. The working-tree
   `.env` is now untracked so it won't be re-committed, but history is unchanged
   (rewriting it is destructive on a shared remote — coordinate with the owner if
   you want a `git filter-repo`/BFG scrub; rotation is the real fix).
2. **When you next push**, expect ~60 *deletions* (the SQLite DBs, the
   `investigations/crawled/` HTML cache, and stale `.pyc`) — these are runtime
   artifacts now correctly git-ignored, not lost work.

---

## What changed, by phase

| Phase | Theme | Key outcome |
|------|-------|-------------|
| 0 | Safety net | `.gitignore`; untracked `.env`/DBs/cache/`.pyc`; baseline commits |
| 1 | Review | `CODE_REVIEW.md` — findings mapped to SOLID/OOP/DSA + bugs/security |
| 2 | Tests | 44 characterization tests pinning current behavior (no network) |
| 3 | Persistence (DRY/DIP) | `db.py` connection factory + `BaseRepository`; 3 repos |
| 4 | Tor/config (DRY/SRP) | one `tor_session.py`; lazy, cached Tor-port probing |
| 5 | Providers (OCP/SRP) | `providers.py` registry; **live key reads** (reload-bug fix) |
| 6 | Web layer (SRP) | `app.py` → `create_app()` + 5 blueprints + 2 services |
| 7 | Correctness/DSA | wired up dead `tor_utils`; removed dead code; normalized dedup |
| 8 | Frontend | removed dead `/api/config`; wired "New Tor Identity" button |
| 9 | Hygiene/docs | fixed `requirements`, `.dockerignore`, Docker host, README, `.env.example` |
| 10 | Verify | py_compile + 74 tests + ruff + import smoke all green |

### Architecture before → after
- **14 modules, one 622-line `app.py` god-module, 0 tests** →
- **24 focused modules + a `create_app()` factory + 5 blueprints, 74 tests.**

New modules: `db.py`, `tor_session.py`, `providers.py`, `env_manager.py`,
`pipeline.py`, `web_routes.py`, `api_config.py`, `api_investigations.py`,
`api_seeds.py`, `api_tor.py`.

---

## SOLID / OOP / DSA mapping

- **SRP** — `app.py` split into web routes (blueprints) vs. services
  (`pipeline.InvestigationPipeline`, `env_manager`); `obscura_config` no longer
  does network I/O at import.
- **OCP** — adding an LLM provider is now **one entry** in `providers.PROVIDERS`
  / `STATIC_MODELS`, instead of editing parallel `if/elif` chains in `llm.py`,
  `health.py`, and `app.py`.
- **DIP** — modules depend on `db.connect()` and live config accessors, not on
  copy-pasted connection code or import-time constant snapshots.
- **DRY** — removed 3× duplicated `_connect()`, 2× `get_tor_session()`, and 3×
  provider-detection chains.
- **OOP** — repository classes (`InvestigationRepository`/`SeedRepository`/
  `PresetRepository` over `BaseRepository`), the provider registry dataclasses,
  and a dependency-injected pipeline.
- **DSA** — search-result de-duplication now uses a *normalized* key
  (scheme-insensitive, host-lowercased) so `http`/`https`/case variants of one
  onion collapse to a single result. (The hot paths are I/O-bound; no other
  structure was algorithmically deficient, so none was force-changed.)

---

## Bugs fixed

- **Runtime key save had no effect** — config was snapshotted at import and the
  code resorted to `importlib.reload`, which doesn't update already-bound names.
  Keys are now read live; the reload hack is gone.
- **`tor_utils.py` was 100% dead** — now wired to `POST /api/tor/newnym`
  (rotate circuit + report new exit IP) with a UI button.
- **Local llama.cpp models incorrectly required an OpenAI key** — the provider
  registry returns no cloud provider for dynamic local models, so no key is
  demanded.
- **Malformed investigate params returned HTTP 500** — numeric tuning fields are
  now coerced safely to their defaults.
- **`flask` was missing from `requirements.txt`** — the Docker build would have
  failed at `python app.py`. Added (and dropped the never-imported `streamlit`).
- Removed dead functions (`seeds.mark_loaded/get_uncrawled/get_unloaded/
  seed_urls_from_sources`, `presets.get_preset_by_key`), unused imports, and
  fixed all ruff findings.

## Security

- `.env` untracked + `.gitignore`; `.env.example` added for onboarding.
- Dev server now binds **127.0.0.1 by default** (no auth + Tor/LLM spend); the
  Docker image sets `OBSCURA_HOST=0.0.0.0` so `docker run -p` still works.
  Override natively with `OBSCURA_HOST`/`OBSCURA_PORT`.

---

## Intentional behavior changes (verify these match your expectations)

1. **Bind host** default `0.0.0.0` → `127.0.0.1` (Docker unaffected; override via env).
2. **llama.cpp** models no longer require `OPENAI_API_KEY`.
3. **Search dedup** is now scheme/case-insensitive (may merge previously-distinct
   `http`/`https` duplicates).
4. **Provider keys** apply immediately on UI save (no restart).
5. `streamlit` removed from `requirements.txt` (it was unused).

Everything else is behavior-preserving and asserted by the test suite.

## Testing

`pytest` (74 tests, no network/Tor/keys needed):
- pure logic: env cleaning, model resolution/gating, search parsers/scoring/dedup,
  LLM formatting, markdown→PDF, scrape truncation;
- the full SQLite persistence API against a temp DB;
- the provider registry; the `tor_session` factory + lazy ports;
- the `InvestigationPipeline` (DI'd fakes); and the **Flask route layer** via the
  test client (every blueprint exercised).

Run: `python -m pytest` · Lint: `ruff check .`

## Recommended follow-ups (not done — need your call / a browser)

- Rotate the leaked OpenRouter key (see top); optionally scrub history.
- Pin dependency versions in `requirements.txt` for reproducible builds.
- Deeper **frontend** modularization (ES modules + a JS test harness) was
  deliberately *not* attempted — there's no way to verify UI behavior here
  without a browser + live Tor/LLM stack. The backend was the right place for
  the SOLID/OOP work; the frontend got only safe, additive changes.
- Add light validation (length/newline caps) to the provider-save endpoint.
