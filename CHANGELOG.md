# Changelog

All notable changes to OBSCURA are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased] — 0.4.0 (in progress)

Theme: **deeper dark-web reach + retrieval-grounded reporting.**

### Planned
- **Deep search** — recursive, relevance-guided crawling beyond the first hop:
  onion-link extraction from crawled pages and a scored crawl frontier.
- **RAG** — embed crawled content into a vector store and retrieve the most
  relevant chunks for the report, replacing fixed truncation.
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
