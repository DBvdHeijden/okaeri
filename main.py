"""Run okaeri, or manage it as a background service that starts at login.

    uv run main.py              # run the server in this terminal
    uv run main.py install      # run it in the background: launchd on macOS, systemd on Linux
    uv run main.py uninstall | restart | update | status | logs
"""

import argparse
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path

import uvicorn

from app import settings
from app.embed import MODEL, MODEL_DIR
from app.sources import BY_ID
from app.store import default_path, open_store

ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = 12362
PORT = int(os.environ.get("OKAERI_PORT", DEFAULT_PORT))
URL = f"http://localhost:{PORT}"
LOG = ROOT / "data" / "okaeri.log"
MAX_LOG_BYTES = 5 * 2**20
MAC, LINUX = sys.platform == "darwin", sys.platform.startswith("linux")

# One service per port, so a second checkout on another port doesn't replace the first.
NAME = "okaeri" if PORT == DEFAULT_PORT else f"okaeri-{PORT}"
LABEL = f"dev.{NAME}"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
UNIT = Path.home() / ".config" / "systemd" / "user" / f"{NAME}.service"

# PYTHONUNBUFFERED: output goes to a file, which Python would otherwise only write in big chunks.
PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{label}</string>
    <key>ProgramArguments</key>
    <array><string>{uv}</string><string>run</string><string>--frozen</string><string>main.py</string></array>
    <key>WorkingDirectory</key><string>{root}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OKAERI_PORT</key><string>{port}</string>
        <key>PYTHONUNBUFFERED</key><string>1</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ProcessType</key><string>Background</string>
    <key>StandardOutPath</key><string>{log}</string>
    <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""

UNIT_TEMPLATE = """\
[Unit]
Description=okaeri, a localhost homepage

[Service]
WorkingDirectory={root}
ExecStart="{uv}" run --frozen main.py
Environment=OKAERI_PORT={port} PYTHONUNBUFFERED=1
Restart=on-failure
Nice=19
CPUSchedulingPolicy=idle
StandardOutput=append:{log}
StandardError=append:{log}

[Install]
WantedBy=default.target
"""


def rotate_log() -> None:
    if not LOG.exists() or LOG.stat().st_size < MAX_LOG_BYTES:
        return
    started_by_service = os.path.samestat(os.fstat(sys.stdout.fileno()), LOG.stat())
    LOG.replace(LOG.with_name("okaeri.log.1"))
    if started_by_service:
        # launchd/systemd opened the log for us and would keep writing to the renamed file; switch to a fresh one.
        fd = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(fd, sys.stdout.fileno())
        os.dup2(fd, sys.stderr.fileno())
        os.close(fd)


def serve() -> None:
    rotate_log()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "app.server:app",
        host="127.0.0.1",
        port=PORT,
        reload=os.environ.get("OKAERI_RELOAD") == "1",
        workers=1,
    )


# --- helpers -------------------------------------------------------------------


def run(*args: str) -> str:
    done = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"`{' '.join(args)}` failed:\n{(done.stderr or done.stdout).strip()}")
    return done.stdout


def succeeds(*args: str) -> bool:
    return subprocess.run(args, capture_output=True).returncode == 0


def wait_for(condition, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.25)
    return True


def service_target() -> str:
    return f"gui/{os.getuid()}/{LABEL}"


def installed() -> bool:
    return (PLIST if MAC else UNIT).exists()


def running() -> bool:
    if MAC:
        return "state = running" in subprocess.run(["launchctl", "print", service_target()], capture_output=True, text=True).stdout
    return succeeds("systemctl", "--user", "is-active", "--quiet", NAME)


def port_in_use() -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def answering() -> bool:
    try:
        urllib.request.urlopen(URL, timeout=2)
        return True
    except OSError:
        return False


def unregister() -> None:
    """Stop and unregister the service; fine if it isn't registered."""
    if MAC:
        succeeds("launchctl", "bootout", service_target())
        wait_for(lambda: not succeeds("launchctl", "print", service_target()), 10)  # bootout finishes asynchronously
    else:
        succeeds("systemctl", "--user", "disable", "--now", NAME)


def require_installed() -> None:
    if not installed():
        sys.exit("okaeri isn't installed as a service. Install it with: uv run main.py install")


def local_time(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")


# --- commands ------------------------------------------------------------------


def install() -> None:
    if not (MAC or LINUX):
        sys.exit(f"Installing as a service isn't supported on {sys.platform} yet. Run it in a terminal instead: uv run main.py")
    uv = shutil.which("uv")
    if not uv:
        sys.exit("Can't find uv on your PATH. Install it from https://docs.astral.sh/uv/")
    if port_in_use() and not running():
        sys.exit(
            f"Port {PORT} is already in use by another program. Stop that program, or use another port:\n"
            f"  OKAERI_PORT={PORT + 1} uv run main.py install   (then pass OKAERI_PORT to the other commands too)"
        )
    unregister()  # so installing again replaces the old service
    if not wait_for(lambda: not port_in_use(), 10):
        sys.exit(f"Port {PORT} is still in use after stopping the old service.")
    LOG.parent.mkdir(exist_ok=True)
    values = {"label": LABEL, "uv": uv, "root": ROOT, "port": PORT, "log": LOG}
    if MAC:
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        PLIST.write_text(PLIST_TEMPLATE.format(**values))
        run("launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST))
    else:
        UNIT.parent.mkdir(parents=True, exist_ok=True)
        UNIT.write_text(UNIT_TEMPLATE.format(**values))
        run("systemctl", "--user", "daemon-reload")
        run("systemctl", "--user", "enable", "--now", NAME)
    if not wait_for(answering, 30):
        sys.exit(f"Installed, but {URL} isn't answering yet. See what happened with: uv run main.py logs")
    print(f"okaeri is running at {URL} and starts whenever you log in.")
    print("Open it to pick your sources. Tip: set it as your browser's homepage or new tab page.")


def uninstall() -> None:
    require_installed()
    unregister()
    (PLIST if MAC else UNIT).unlink()
    if LINUX:
        run("systemctl", "--user", "daemon-reload")
    data = ROOT / "data"
    print("Uninstalled the service.")
    print(f"Your data is still there: {data} (database with your reading history, the model, the log) and settings.json.")
    print(f"To delete it too: rm -rf {data} {ROOT / 'settings.json'}")


def restart() -> None:
    require_installed()
    if MAC:
        run("launchctl", "kickstart", "-k", service_target())
    else:
        run("systemctl", "--user", "restart", NAME)
    if not wait_for(answering, 30):
        sys.exit(f"Restarted, but {URL} isn't answering yet. See what happened with: uv run main.py logs")
    print(f"Restarted; okaeri is running at {URL}")


def update() -> None:
    if run("git", "status", "--porcelain", "--untracked-files=no").strip():
        sys.exit("You have local changes (see `git status`). Commit or stash them, then update again.")
    pull = subprocess.run(["git", "pull", "--ff-only"], cwd=ROOT, capture_output=True, text=True)
    if pull.returncode != 0:
        sys.exit(f"Couldn't fast-forward to the latest version, so nothing changed:\n{pull.stderr.strip()}")
    print(pull.stdout.strip())
    run("uv", "sync", "--frozen")
    if installed():
        restart()
    else:
        print("Updated. Start it with: uv run main.py install")


def logs() -> None:
    if not LOG.exists():
        sys.exit(f"No log yet at {LOG}")
    with LOG.open(errors="replace") as f:
        print("".join(deque(f, 50)), end="")


def status() -> None:
    store = open_store(default_path())
    enabled = {i: BY_ID[i] for i in settings.enabled_sources() if i in BY_ID}
    feed = store.articles(enabled)
    embedded = store.embedded_keys(MODEL)
    fetched_at, failing = store.last_fetch()
    embed_run = store.last_embed_run()
    model_bytes = sum(f.stat().st_size for f in MODEL_DIR.rglob("*") if f.is_file())
    service = "not installed" if not installed() else "installed, running" if running() else "installed, NOT running"
    rows = {
        "version": run("git", "log", "-1", "--format=%h (%cs)").strip(),
        "service": f"{service} ({LABEL if MAC else NAME})",
        "url": f"{URL} ({'answering' if answering() else 'not answering'})",
        "sources": f"{len(enabled)} enabled",
        "feed": f"{len(feed)} articles, {sum(a.key in embedded for a in feed)} embedded",
        "last fetch": f"{local_time(fetched_at)}, {failing} feeds failing" if fetched_at else "never",
        "last embed": f"{local_time(embed_run[0])}, {embed_run[1]}" if embed_run else "never",
        "model": f"on disk, {model_bytes / 2**20:.0f} MB" if model_bytes else "not downloaded yet (happens on the first embed run)",
        "log": f"{LOG} ({LOG.stat().st_size / 2**20:.1f} MB)" if LOG.exists() else f"{LOG} (none yet)",
    }
    for name, value in rows.items():
        print(f"{name:<12}{value}")


COMMANDS = {f.__name__: f for f in (install, uninstall, restart, update, status, logs)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run okaeri, or manage it as a background service.")
    parser.add_argument("command", nargs="?", choices=COMMANDS, help="leave out to run the server in this terminal")
    command = parser.parse_args().command
    if command:
        COMMANDS[command]()
    else:
        serve()
