# Changelog

All notable changes to OBSCURA are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased] — 0.4.0 (in progress)

Theme: **deeper dark-web reach + retrieval-grounded reporting.**

### Added
- **Deep search** (`deep_search.py`) — relevance-guided best-first crawl that
  follows links out of crawled pages into onion services, bounded by a scored
  priority frontier (max depth + page budget). Opt-in per investigation
  (`deep=true`).
- **RAG** (`rag.py`) — crawled content is chunked, embedded **locally**
  (FastEmbed/ONNX, no data egress), indexed (Chroma or in-memory), and the most
  query-relevant chunks are retrieved for the report instead of truncating.
  Opt-in per investigation (`use_rag=true`).
- Pipeline + `/api/investigate` wired for both stages; defaults preserve the
  classic single-hop flow.
- **Parallel deep crawl** — the frontier is fetched in concurrent waves
  (`max_workers`), turning wall-clock `O(pages × latency)` into
  ~`O(pages / workers × latency)` while keeping relevance order.
- **Map-reduce summarization** (`summarizer.py`) — content is batched to a token
  budget, each batch is summarized (map), then synthesized into the final report
  (reduce, recursive if needed). The model now processes **all** gathered
  content instead of only what fit in one prompt; single-batch investigations
  still make exactly one call.

### Planned
- **Automation (tentative)** — optional n8n workflows to trigger/schedule
  investigations via the API.

## [0.3.1] — 2026-06-13

First packaged release. OBSCURA is now distributable as a self-contained tool:
run it from the terminal, in Docker, or as a systemd service.

### Added
- **`obscura` CLI** (`cli.py`) — operator front-end with `start`, `stop`,
  `logs`, `status`, `version`, and `doctor` subcommands, in both native and
  `--docker` modes.
- **Packaging** (`pyproject.toml`) — `pip install -e .` exposes the `obscura`
  console command; version is sourced from `__version__.py`.
- **`docker-compose.yml`** — one-command container stack
  (`docker compose up --build`) with persistent volumes for the database and
  logs, a healthcheck against `/api/version`, and localhost-only host binding.
- **systemd service** (`deploy/obscura.service` + `deploy/install.sh`) — enables
  `sudo systemctl start obscura`, running the containerized app so the code
  lives inside the image.
- **File logging** — the app writes a rotating log to `logs/obscura.log`
  (override with `OBSCURA_LOG_DIR`), tailed by `obscura logs`.
- **`/api/version`** endpoint and a version line in the startup banner.

### Notes
- Defaults remain localhost-only (no auth); expose deliberately via
  `OBSCURA_HOST` / the compose port mapping.
