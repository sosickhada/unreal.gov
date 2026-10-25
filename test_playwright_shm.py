"""Test Chromium through Playwright with an isolated /dev/shm profile."""
import asyncio
import tempfile
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    with tempfile.TemporaryDirectory(prefix="unreal-test-", dir="/dev/shm") as profile:
        print("RAM profile:", profile, flush=True)
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=profile,
                headless=True,
                viewport={"width": 1080, "height": 1350},
                timeout=45000,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-gpu", "--disable-extensions",
                      "--disable-background-networking", "--no-first-run"],
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.set_content("<html><body>PLAYWRIGHT_OK</body></html>")
                print("Result:", await page.locator("body").inner_text(), flush=True)
            finally:
                await context.close()

if __name__ == "__main__":
    asyncio.run(main())
