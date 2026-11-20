"""Run the team workspace on a Windows PC."""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Queue
from secrets import choice
from tempfile import NamedTemporaryFile
from threading import Event, Thread
from urllib.request import ProxyHandler, build_opener

import uvicorn
from dotenv import dotenv_values

from app.workspaces import INVITE_ENVS, PC_INVITE_ALPHABET, normalize_pc_invite, validate_invites

PROJECT = Path(__file__).resolve().parents[1]
INVITE_FILE = PROJECT / ".env.pc-share"
BACKEND_ENV = PROJECT / "backend" / ".env"
LOCAL_PORT = 8765
LOCAL_URL = f"http://127.0.0.1:{LOCAL_PORT}"
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com(?=[\s/|]|$)")


def workspace_is_running() -> bool:
    try:
        with build_opener(ProxyHandler({})).open(f"{LOCAL_URL}/api/health", timeout=0.5) as response:
            health = json.loads(response.read(16_384))
    except (OSError, ValueError):
        return False
    return isinstance(health, dict) and health.get("ok") is True and health.get("pc_share") is True


def announce_when_ready(open_browser: bool, share_url: str = "") -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if workspace_is_running():
            if share_url:
                print(f"TEAM LINK: {share_url}", flush=True)
                print("Keep this window open while the team is using Re AI.", flush=True)
            if not open_browser:
                return
            try:
                if webbrowser.open(LOCAL_URL, new=2):
                    return
            except (OSError, webbrowser.Error):
                pass
            break
        time.sleep(0.25)
    print(f"Open {LOCAL_URL} in your browser.", flush=True)


@contextmanager
def team_tunnel():
    local_exe = PROJECT / "cloudflared.exe"
    executable = str(local_exe) if local_exe.is_file() else shutil.which("cloudflared")
    if not executable:
        raise SystemExit("Put the official cloudflared.exe next to 05_run_team_share.bat.")
    ready = Queue()
    stopping = Event()
    try:
        tunnel = subprocess.Popen(
            [executable, "tunnel", "--url", LOCAL_URL],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        raise SystemExit("Could not start cloudflared. Check the Windows executable in the project folder.") from None

    def read_tunnel_output():
        address = ""
        announced = False
        with tunnel.stdout as output:
            for line in output:
                print(line.rstrip(), flush=True)
                if not address and (match := TUNNEL_URL.search(line)):
                    address = match.group()
                if not announced and address and "Registered tunnel connection" in line:
                    ready.put(address)
                    announced = True
        if announced and not stopping.is_set():
            print("Team tunnel stopped. Restart this launcher to get a working team link.", flush=True)
        ready.put(None)

    Thread(target=read_tunnel_output, daemon=True).start()
    try:
        try:
            address = ready.get(timeout=60)
        except Empty:
            raise SystemExit("The Cloudflare connection did not become ready. Check the tunnel messages above.") from None
        if not address:
            raise SystemExit("The Cloudflare connection stopped. Check the tunnel messages above.")
        yield address
    finally:
        stopping.set()
        if tunnel.poll() is None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait()


def configure() -> None:
    settings = dotenv_values(BACKEND_ENV, encoding="utf-8-sig")
    provider = (os.getenv("REAI_PC_CHAT_PROVIDER") or settings.get("REAI_PC_CHAT_PROVIDER") or "mock").strip().lower()
    flags = set(sys.argv[1:])
    if flags - {"chatgpt", "invite", "browser", "share"}:
        raise SystemExit("Usage: 04_run_pc_share.bat [chatgpt] [invite] [browser] [share]")
    if "chatgpt" in flags:
        provider = "chatgpt"
    if provider not in {"openai", "mock", "chatgpt"}:
        raise SystemExit("Set REAI_PC_CHAT_PROVIDER to openai or mock, or run 04_run_pc_share.bat chatgpt.")
    if provider == "chatgpt":
        try:
            import jwt
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ImportError:
            raise SystemExit("Install the ChatGPT sign-in dependency: .venv\\Scripts\\python.exe -m pip install PyJWT[crypto]")
    if provider == "openai":
        api_key = (os.getenv("OPENAI_API_KEY") or settings.get("OPENAI_API_KEY") or "").strip()
        if not api_key or api_key == "YOUR_API_KEY":
            raise SystemExit("Set OPENAI_API_KEY in backend/.env before starting OpenAI mode.")
        os.environ["OPENAI_API_KEY"] = api_key

    os.environ.update(
        REAI_ENV="online-demo",
        REAI_PC_SHARE="1",
        REAI_ACCOUNT_LOGIN="0" if "invite" in flags else "1",
        REAI_CHATGPT_LOCAL="1" if provider == "chatgpt" else "0",
        REAI_CHAT_PROVIDER="mock" if provider == "chatgpt" else provider,
        REAI_DATA_DIR=str(PROJECT / "data" / "pc-share"),
    )
    if "invite" not in flags:
        return

    invites = dotenv_values(INVITE_FILE) if INVITE_FILE.exists() else {}
    updates = {}
    for company in ("demo-a", "demo-e", "demo-b"):
        key = INVITE_ENVS[company]
        if not normalize_pc_invite(invites.get(key) or ""):
            updates[key] = "-".join(
                "".join(choice(PC_INVITE_ALPHABET) for _ in range(4))
                for _ in range(3)
            )
    invites.update(updates)
    for key in INVITE_ENVS.values():
        os.environ[key] = invites.get(key) or ""
    validate_invites()
    if updates:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=PROJECT, delete=False) as file:
            temp_path = Path(file.name)
            for key in INVITE_ENVS.values():
                if invites.get(key):
                    file.write(f"{key}={invites[key]}\n")
        try:
            temp_path.replace(INVITE_FILE)
        finally:
            temp_path.unlink(missing_ok=True)


def run_server(open_browser: bool, share_url: str = "") -> None:
    print(f"Open {LOCAL_URL} to check Re AI.", flush=True)
    print(f"Conversation mode: {'chatgpt (local browser)' if os.environ['REAI_CHATGPT_LOCAL'] == '1' else os.environ['REAI_CHAT_PROVIDER']}", flush=True)
    if os.environ["REAI_ACCOUNT_LOGIN"] == "1":
        print("Team access: company accounts", flush=True)
    else:
        print(f"Company invite codes: {INVITE_FILE}", flush=True)
    if open_browser or share_url:
        Thread(target=announce_when_ready, args=(open_browser, share_url), daemon=True).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=LOCAL_PORT, proxy_headers=False, access_log=os.environ["REAI_CHATGPT_LOCAL"] != "1")


if __name__ == "__main__":
    configure()
    open_browser = "browser" in sys.argv[1:]
    if "share" in sys.argv[1:]:
        if workspace_is_running():
            raise SystemExit("Re AI is already running. Stop its server before opening the team share.")
        with team_tunnel() as share_url:
            os.environ["REAI_PC_SHARE_URL"] = share_url
            run_server(open_browser, share_url)
    elif open_browser and workspace_is_running():
        announce_when_ready(True)
    else:
        run_server(open_browser)
