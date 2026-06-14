#!/usr/bin/env python3
"""
cli.py — the `obscura` terminal tool.

A thin operator front-end over the OBSCURA web app. It does not contain any
business logic; it just starts/stops the server (natively or via Docker
Compose) and tails logs, so an operator can drive everything from one command:

    obscura start            # run natively in the foreground, stream logs
    obscura start --docker   # run the container stack via docker compose
    obscura logs -f          # follow logs (native log file or container logs)
    obscura status           # is it up? what version?
    obscura stop --docker    # tear the container stack down
    obscura version
    obscura doctor           # check the host has what it needs

The systemd unit (deploy/obscura.service) simply runs `obscura start --docker`
in the foreground and lets systemd own the process lifecycle — that is what
makes `sudo systemctl start obscura` work.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from __version__ import __version__

# Directory that ships the app + packaging files. Resolving against this file
# means the CLI works whether it is run as `python cli.py` from a checkout or as
# the installed `obscura` console script (the data files sit next to it).
APP_DIR = Path(__file__).resolve().parent
COMPOSE_FILE = APP_DIR / "docker-compose.yml"
DEFAULT_LOG_FILE = Path(
    os.environ.get("OBSCURA_LOG_DIR", str(APP_DIR / "logs"))
) / "obscura.log"


# ── helpers ──────────────────────────────────────────────────────────────────

def _die(msg: str, code: int = 1) -> "int":
    print(f"obscura: error: {msg}", file=sys.stderr)
    return code


def _compose_cmd() -> list[str] | None:
    """Return the docker compose invocation, or None if Docker is unavailable.
    Prefers the v2 plugin (`docker compose`); falls back to legacy
    `docker-compose`."""
    if shutil.which("docker"):
        try:
            subprocess.run(
                ["docker", "compose", "version"],
                check=True, capture_output=True,
            )
            return ["docker", "compose"]
        except (subprocess.CalledProcessError, OSError):
            pass
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return None


def _run(cmd: list[str], **kwargs) -> int:
    """Run a command, inheriting stdio, and return its exit code."""
    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    try:
        return subprocess.call(cmd, **kwargs)
    except FileNotFoundError:
        return _die(f"command not found: {cmd[0]}")
    except KeyboardInterrupt:
        return 130


# ── commands ───────────────────────────────────────────────────────────────

def cmd_start(args: argparse.Namespace) -> int:
    env = os.environ.copy()
    if args.host:
        env["OBSCURA_HOST"] = args.host
    if args.port:
        env["OBSCURA_PORT"] = str(args.port)

    if args.docker:
        compose = _compose_cmd()
        if not compose:
            return _die("Docker is not installed or the compose plugin is missing.")
        if not COMPOSE_FILE.exists():
            return _die(f"compose file not found: {COMPOSE_FILE}")
        cmd = [*compose, "-f", str(COMPOSE_FILE), "up"]
        if args.build:
            cmd.append("--build")
        if args.detach:
            cmd.append("-d")
        return _run(cmd, env=env)

    # Native: hand off to the Flask app in the foreground. exec-style replace so
    # signals (Ctrl-C, systemd SIGTERM) reach the server directly.
    app = APP_DIR / "app.py"
    if not app.exists():
        return _die(f"app.py not found at {app}")
    if args.detach:
        return _die("--detach is only supported with --docker; "
                    "use systemd or `nohup` for native background runs.")
    print(f"Starting OBSCURA {__version__} (native) — logs → {DEFAULT_LOG_FILE}",
          file=sys.stderr)
    os.chdir(APP_DIR)
    os.execvpe(sys.executable, [sys.executable, str(app)], env)


def cmd_stop(args: argparse.Namespace) -> int:
    if args.docker:
        compose = _compose_cmd()
        if not compose:
            return _die("Docker is not installed or the compose plugin is missing.")
        return _run([*compose, "-f", str(COMPOSE_FILE), "down"])
    print("Native foreground runs stop with Ctrl-C. Under systemd use "
          "`sudo systemctl stop obscura`.", file=sys.stderr)
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    if args.docker:
        compose = _compose_cmd()
        if not compose:
            return _die("Docker is not installed or the compose plugin is missing.")
        cmd = [*compose, "-f", str(COMPOSE_FILE), "logs"]
        if args.follow:
            cmd.append("-f")
        cmd += ["--tail", str(args.lines)]
        return _run(cmd)

    if not DEFAULT_LOG_FILE.exists():
        return _die(f"no log file yet at {DEFAULT_LOG_FILE} — has OBSCURA run?")
    tail = ["tail", f"-n{args.lines}"]
    if args.follow:
        tail.append("-f")
    tail.append(str(DEFAULT_LOG_FILE))
    return _run(tail)


def cmd_status(args: argparse.Namespace) -> int:
    if args.docker:
        compose = _compose_cmd()
        if not compose:
            return _die("Docker is not installed or the compose plugin is missing.")
        return _run([*compose, "-f", str(COMPOSE_FILE), "ps"])

    # Native: probe the version endpoint.
    host = os.environ.get("OBSCURA_HOST", "127.0.0.1")
    port = os.environ.get("OBSCURA_PORT", "8501")
    host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{host}:{port}/api/version"
    try:
        import json
        import urllib.request
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310 (local)
            data = json.load(resp)
        print(f"OBSCURA is UP — version {data.get('version')} at {url}")
        return 0
    except Exception:
        print(f"OBSCURA appears DOWN (no response at {url})")
        return 1


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"OBSCURA {__version__}")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    print(f"OBSCURA {__version__} — environment check\n")
    ok = True

    def check(label: str, value: str | None, required: bool = False) -> None:
        nonlocal ok
        mark = "✓" if value else ("✗" if required else "—")
        print(f"  [{mark}] {label}: {value or 'not found'}")
        if required and not value:
            ok = False

    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    check("Python", py, required=True)
    check("app.py", str(APP_DIR / 'app.py') if (APP_DIR / 'app.py').exists() else None,
          required=True)
    check("docker", shutil.which("docker"))
    check("docker compose", " ".join(_compose_cmd()) if _compose_cmd() else None)
    check("tor", shutil.which("tor"))
    check("docker-compose.yml", str(COMPOSE_FILE) if COMPOSE_FILE.exists() else None)
    log_dir = DEFAULT_LOG_FILE.parent
    check("log dir writable", str(log_dir) if os.access(
        log_dir if log_dir.exists() else log_dir.parent, os.W_OK) else None)

    print("\nResult:", "READY ✓" if ok else "missing required components ✗")
    return 0 if ok else 1


# ── entry point ──────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="obscura",
        description="OBSCURA — dark-web OSINT toolkit operator CLI.",
    )
    p.add_argument("-V", "--version", action="version",
                   version=f"OBSCURA {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("start", help="start the OBSCURA web app (foreground)")
    sp.add_argument("--docker", action="store_true",
                    help="run via docker compose instead of natively")
    sp.add_argument("--build", action="store_true",
                    help="(docker) rebuild the image before starting")
    sp.add_argument("--detach", "-d", action="store_true",
                    help="(docker) run in the background")
    sp.add_argument("--host", help="bind host (default 127.0.0.1)")
    sp.add_argument("--port", type=int, help="bind port (default 8501)")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("stop", help="stop OBSCURA (docker compose stack)")
    sp.add_argument("--docker", action="store_true")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("logs", help="tail OBSCURA logs")
    sp.add_argument("--docker", action="store_true")
    sp.add_argument("-f", "--follow", action="store_true", help="follow output")
    sp.add_argument("-n", "--lines", type=int, default=200,
                    help="lines of history to show (default 200)")
    sp.set_defaults(func=cmd_logs)

    sp = sub.add_parser("status", help="show whether OBSCURA is running")
    sp.add_argument("--docker", action="store_true")
    sp.set_defaults(func=cmd_status)

    sub.add_parser("version", help="print the version").set_defaults(func=cmd_version)
    sub.add_parser("doctor", help="check the host environment").set_defaults(
        func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
