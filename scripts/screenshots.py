"""Screenshot every demo tab into docs/screenshots/ (used for the README and for visual checks).

    python scripts/screenshots.py            # all demos
    python scripts/screenshots.py 02         # only demos whose folder starts with 02
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "subsurface-app-builder" / "scripts"))
from screenshot_app import capture  # noqa: E402

if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    demos = sorted(p for p in (ROOT / "demos").iterdir() if (p / "app.py").exists() and p.name.startswith(only))
    bad = sum(capture(d / "app.py", ROOT / "docs" / "screenshots", prefix=d.name, port=8611 + i, cwd=ROOT)
              for i, d in enumerate(demos))
    sys.exit(1 if bad else 0)
