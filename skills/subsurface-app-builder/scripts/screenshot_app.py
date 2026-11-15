"""Start a Streamlit app, click through its tabs and save one screenshot per tab.

A headless AppTest run cannot see a blank or mis-scaled chart; these images can. Read them after
every visual change.

Usage:
    python screenshot_app.py app.py shots/
    python screenshot_app.py app.py shots/ --prefix wells --port 8620 --width 1600 --height 1000

Needs once:  pip install playwright  &&  python -m playwright install chromium
Prints one line per image with the number of error boxes found on the page; exits 1 if any.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def wait_for(url: str, timeout: float = 90) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    raise TimeoutError(f"app did not start: {url}")


def capture(app: Path, out: Path, prefix: str = "", port: int = 8611, width: int = 1600, height: int = 1000,
            settle_ms: int = 2500, cwd: Path | None = None) -> int:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    prefix = prefix or app.resolve().parent.name
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(port),
                             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                            cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    problems = 0
    try:
        wait_for(f"http://localhost:{port}/_stcore/health")
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(f"http://localhost:{port}")
            page.wait_for_selector('[data-testid="stAppViewContainer"]', timeout=120_000)
            page.wait_for_timeout(3000)
            tabs = page.locator('[data-testid="stTab"]')
            n = tabs.count()
            for i in range(max(n, 1)):
                label = "page"
                if n:
                    tabs.nth(i).click()
                    label = tabs.nth(i).inner_text().strip().lower().replace(" ", "_").replace("-", "_").replace("/", "_")
                page.wait_for_timeout(1500)
                try:  # the running indicator disappears when the script has finished
                    page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=90_000)
                except Exception:
                    pass
                page.wait_for_timeout(settle_ms)
                dst = out / f"{prefix}_{i + 1}_{label}.png"
                page.screenshot(path=str(dst))
                errors = page.locator('[data-testid="stException"]').count()
                problems += errors
                print(f"{dst}  exceptions_on_page={errors}")
            browser.close()
    finally:
        proc.kill()
        proc.wait()
    return problems


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("app", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--port", type=int, default=8611)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    a = ap.parse_args()
    sys.exit(1 if capture(a.app, a.out, a.prefix, a.port, a.width, a.height) else 0)
