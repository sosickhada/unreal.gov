"""Local browser transport diagnostic, bounded by caller. No app config or API clients."""
import asyncio
import os
from pathlib import Path
import tempfile
os.environ['DEBUG']='pw:browser'
from playwright.async_api import async_playwright
from chromium_diagnostic import tree

async def main():
    async def report():
        await asyncio.sleep(8)
        print('PROCESS_TREE',tree(os.getpid()),flush=True)
    watch=asyncio.create_task(report())
    try:
        async with async_playwright() as p:
            with tempfile.TemporaryDirectory(prefix='unreal-probe-',dir='/dev/shm') as profile:
                print('LAUNCH',flush=True)
                context=await p.chromium.launch_persistent_context(profile,headless=True,timeout=15000,args=['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--disable-extensions','--disable-background-networking','--no-first-run'])
                print('CONTEXT_READY',flush=True)
                await context.close()
                print('CONTEXT_CLOSED',flush=True)
    finally:
        watch.cancel()
        print('PROBE_FINISH',flush=True)
asyncio.run(main())
