"""Read-only Chromium startup diagnostics for the cloud renderer.

Run: .venv/bin/python diagnose_chromium.py
Does not change running services or application data.
"""
import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path

from playwright.async_api import async_playwright


def memory():
    try:
        lines = Path("/proc/meminfo").read_text().splitlines()
        keys = ("MemTotal:", "MemAvailable:", "SwapTotal:", "SwapFree:")
        return " | ".join(x.strip() for x in lines if x.startswith(keys))
    except OSError as exc:
        return str(exc)


def standalone(chrome, flags, seconds=12):
    cmd = [str(chrome), "--headless", "--no-sandbox", "--disable-dev-shm-usage",
           "--disable-gpu", "--no-first-run", *flags, "--dump-dom", "about:blank"]
    start = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds)
        stderr = result.stderr.strip().splitlines()
        print(f"  exit={result.returncode} elapsed={time.monotonic()-start:.1f}s "
              f"dom={'<html' in result.stdout.lower()}", flush=True)
        if stderr:
            print("  stderr(last):", stderr[-1][:350], flush=True)
    except subprocess.TimeoutExpired:
        print(f"  timeout after {seconds}s", flush=True)


async def playwright_check():
    async with async_playwright() as p:
        chrome = Path(p.chromium.executable_path)
        print("Chrome executable exists:", chrome.is_file(), flush=True)
        print("Chrome path:", chrome, flush=True)
        print("Memory:", memory(), flush=True)
        if chrome.is_file():
            print("Standalone basic:", flush=True)
            standalone(chrome, [])
            print("Standalone reduced processes:", flush=True)
            standalone(chrome, ["--no-zygote", "--single-process", "--disable-extensions"])
        print("Playwright launch:", flush=True)
        browser = None
        try:
            browser = await asyncio.wait_for(
                p.chromium.launch(headless=True, timeout=15000,
                                  args=["--no-sandbox", "--disable-dev-shm-usage"]),
                timeout=20,
            )
            page = await asyncio.wait_for(browser.new_page(), timeout=10)
            await asyncio.wait_for(page.set_content("<html><body>OK</body></html>"), timeout=10)
            print("Playwright page:", await page.locator("body").inner_text(), flush=True)
        except Exception as exc:
            print(f"Playwright error: {type(exc).__name__}: {str(exc)[:900]}", flush=True)
        finally:
            if browser:
                try:
                    await asyncio.wait_for(browser.close(), timeout=5)
                except Exception:
                    pass


if __name__ == "__main__":
    asyncio.run(playwright_check())
