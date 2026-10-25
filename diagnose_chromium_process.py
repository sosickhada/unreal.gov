"""Non-invasive Chromium startup process diagnostics. No service changes."""
import os
import subprocess
import time
from pathlib import Path

chrome = Path.home() / ".cache/ms-playwright/chromium-1248/chrome-linux64/chrome"
args = [str(chrome), "--headless", "--no-sandbox", "--disable-dev-shm-usage",
        "--disable-gpu", "--disable-extensions", "--no-first-run",
        "--user-data-dir=/tmp/unreal-chrome-diagnostic",
        "--dump-dom", "about:blank"]

def status(pid):
    try:
        lines = Path(f"/proc/{pid}/status").read_text().splitlines()
        return " | ".join(line.strip() for line in lines if line.startswith(
            ("State:", "VmRSS:", "VmSwap:", "Threads:")))
    except (FileNotFoundError, PermissionError):
        return "not running"

def wait_channel(pid):
    try:
        return Path(f"/proc/{pid}/wchan").read_text().strip()
    except (FileNotFoundError, PermissionError):
        return "unavailable"

print("Launching Chromium with isolated temporary profile...", flush=True)
proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        start_new_session=True)
try:
    for sec in (2, 5, 10):
        time.sleep(sec - (0 if sec == 2 else (2 if sec == 5 else 5)))
        print(f"After {sec}s: pid={proc.pid}, exit={proc.poll()}, "
              f"{status(proc.pid)}, wait={wait_channel(proc.pid)}", flush=True)
        if proc.poll() is not None:
            break
    try:
        subprocess.run(["ps", "-eo", "pid,ppid,stat,rss,comm,wchan:25",
                        "--sort=-rss"], timeout=5, check=False)
    except Exception as exc:
        print("ps error:", type(exc).__name__, str(exc)[:200], flush=True)
finally:
    if proc.poll() is None:
        import signal
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
    if proc.stderr:
        import selectors
        selector = selectors.DefaultSelector()
        selector.register(proc.stderr, selectors.EVENT_READ)
        if selector.select(timeout=1):
            data = os.read(proc.stderr.fileno(), 4096)
            print("Chromium stderr:", data.decode(errors="replace")[-1000:], flush=True)
        proc.stderr.close()
    print("Diagnostic Chromium stopped; existing services untouched.", flush=True)
