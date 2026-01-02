from __future__ import annotations

import sys
from pathlib import Path


# Ensure the project root is importable so `import app...` works reliably when
# pytest is executed from different working directories or environments.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
