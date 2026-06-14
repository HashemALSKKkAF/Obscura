# **Obscura**

Obscura is an automated toolkit for **dark web content investigation and analysis**. It enables security researchers and analysts to safely collect, process, and examine data from onion services, helping uncover cyber threats, data leaks, and suspicious activities.

The tool is designed to simplify dark web investigations by combining automated crawling, data extraction, and analysis into a single, easy-to-use workflow.

---

## **Key Capabilities**

* Automated crawling of dark web (.onion) sites
* Data extraction (text, links, metadata)
* Keyword-based threat detection
* Structured report generation
* Modular and extensible architecture

---

## **Why Obscura**

* 🔍 Reduces manual investigation effort
* 🛡️ Minimizes exposure to risky environments
* ⚡ Speeds up large-scale analysis
* 📊 Converts raw data into actionable insights

---

## **System Requirements**

Before running Obscura, make sure you have:

* **Python 3.8+**
* **Tor Browser** (or Tor service running)
* **Git**
* **Windows PowerShell** (Windows) or **bash/zsh** (Linux/Kali)

Obscura can run natively on both Windows and Linux (including Kali Linux). The included `Dockerfile` is optional and only required if you want to run the application inside a container.

---

## **Installation**

### 1. Clone the Repository

```powershell
git clone https://github.com/HashemALSKKkAF/OBSCURA.git
cd OBSCURA
```

---

### 2. Install Python Dependencies

Windows PowerShell:

```powershell
pip install -r requirements.txt
```

Linux / Kali:

```bash
pip install -r requirements.txt
```

---

### 3. Start Tor Service

Obscura requires Tor to access dark web (.onion) sites.

**Option 1: Using Tor Browser**

* Open Tor Browser
* Keep it running in the background

**Option 2: Using Tor (command line)**

Windows PowerShell:

```powershell
tor
```

Linux / Kali:

```bash
tor
```

---

## **How to Run Natively**

Start the app, then open the UI in your browser:

```bash
python app.py
# → http://localhost:8501
```

OBSCURA is a web application — you run investigations from the browser UI, not
via command-line arguments. By default it binds **127.0.0.1** (localhost only),
since it has no authentication and drives Tor crawling + LLM spend. To expose it
on your network deliberately:

```bash
OBSCURA_HOST=0.0.0.0 OBSCURA_PORT=8501 python app.py
```

---

## **The `obscura` Tool (CLI)**

OBSCURA ships with a terminal tool so you can start it, follow logs, and check
status from one command instead of remembering `python app.py` flags. Install
the command from a checkout:

```bash
pip install -e .
```

Then:

```bash
obscura start              # run the app in the foreground, streaming logs
obscura start --docker     # run the containerized stack via docker compose
obscura logs -f            # follow the log file (or container logs with --docker)
obscura status             # is it up? what version?
obscura stop --docker      # tear the container stack down
obscura version            # print the version
obscura doctor             # check the host has Python / Docker / Tor / log dir
```

Logs are written to `logs/obscura.log` (override with `OBSCURA_LOG_DIR`) and the
running version is exposed at `GET /api/version`.

---

## **Run with Docker**

The container bundles its own Tor daemon, Firefox + geckodriver for deep
crawling, and the app — no host Tor required.

```bash
docker compose up --build      # build + run (Ctrl-C to stop)
docker compose up -d           # run detached
docker compose logs -f         # follow logs
docker compose down            # stop & remove
```

The UI is published on `http://127.0.0.1:8501` (localhost only by default).
Edit the port mapping in `docker-compose.yml` to expose it on your LAN. LLM keys
come from `.env` (optional — you can also enter them live in the UI), and the
SQLite database + logs persist in mounted volumes across rebuilds.

---

## **Run as a Service (`systemctl`)**

For an always-on deployment, install the systemd unit. It runs the containerized
app, so the code lives inside the image:

```bash
sudo ./deploy/install.sh        # installs to /opt/obscura + the `obscura` command
sudo systemctl enable obscura   # start on boot
sudo systemctl start obscura
sudo systemctl status obscura
journalctl -u obscura -f        # follow service logs
sudo systemctl stop obscura
```

---

## **Project Structure**

OBSCURA is a Flask web app (JSON API + single-page frontend). The backend is
organized by responsibility:

```
OBSCURA/
├── app.py                 # create_app() factory + logging — registers blueprints
├── cli.py                 # the `obscura` operator CLI (start/logs/status/...)
├── __version__.py         # single source of truth for the version
│
├── web_routes.py          # serves the SPA (index.html + assets)
├── api_config.py          # /api/models, /api/providers, /api/presets, /api/health
├── api_investigations.py  # investigations CRUD, investigate (SSE), resummarize, export
├── api_seeds.py           # /api/seeds CRUD + crawl
├── api_tor.py             # /api/tor/newnym (rotate Tor circuit)
│
├── pipeline.py            # InvestigationPipeline (refine→search→filter→scrape→summarize)
├── providers.py           # LLM provider/model registry (single source of truth)
├── llm.py / llm_utils.py  # LLM construction, retries, prompts, model discovery
├── search.py              # dark-web search-engine aggregation + parsers
├── scrape.py / crawler.py # requests + Selenium crawling tiers
├── tor_session.py         # shared Tor-aware requests.Session factory
├── tor_utils.py           # Tor control-port helpers (NEWNYM, exit IP)
├── env_manager.py         # runtime .env writes + provider status
│
├── db.py                  # shared SQLite connection + BaseRepository
├── investigations.py      # InvestigationRepository
├── seeds.py               # SeedRepository
├── presets.py             # PresetRepository
├── export.py              # Markdown → PDF report generation
├── obscura_config.py      # env/config accessors + lazy Tor port probing
├── constants.py           # shared constants (user-agents)
│
├── index.html / script.js / styles.css   # frontend SPA
├── tests/                 # pytest suite (no network/Tor required)
├── Dockerfile / entrypoint.sh / docker-compose.yml / .dockerignore
├── deploy/                # systemd unit + install.sh (systemctl deployment)
├── pyproject.toml         # packaging + `obscura` console entry point
├── CHANGELOG.md
└── requirements.txt
```

---

## **Configuration**

Configuration lives in a `.env` file. Copy the template and fill in what you need:

```bash
cp .env.example .env
```

You can set LLM provider keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GOOGLE_API_KEY`, `OPENROUTER_API_KEY`), local-model URLs (`OLLAMA_BASE_URL`,
`LLAMA_CPP_BASE_URL`), Tor settings, and the server host/port. Provider keys can
also be entered live from the **Configuration** panel in the UI — they're saved
back to `.env` and take effect immediately. See `.env.example` for the full,
commented list.

> **Never commit `.env`** — it holds secrets and is git-ignored. Share the
> redacted `.env.example` instead.

---

## **Example Workflow**

1. Start Tor (Tor Browser or the `tor` service).
2. Run `python app.py` and open `http://localhost:8501`.
3. Pick an LLM model and a research domain (preset), type a query, and run the
   investigation. OBSCURA refines the query, searches dark-web engines, filters
   and scrapes the best sources, and generates a structured report.
4. Review the report in the UI, export it as **PDF** or **Markdown**, or add
   `.onion` URLs to the **Seed Manager** for deep crawling.

---

## **Use Cases**

* Dark web monitoring
* Threat intelligence (CTI)
* Data breach detection
* Cybercrime investigation
* Security research

---

## **Development**

Run tests:

```powershell
pytest
```

---

## **Contributing**

1. Fork the repository
2. Create a new branch
3. Make changes with proper testing
4. Submit a pull request

---

## **Ethical Use Disclaimer**

This tool is intended **strictly for legal and ethical purposes** such as cybersecurity research and threat analysis. Misuse for illegal activities is strictly prohibited.

---

## **License**

MIT License

---

## **Support**

For issues or feature requests, open an issue on GitHub.
