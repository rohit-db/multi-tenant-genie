import os
import sys
from pathlib import Path

# Bypass the app-level login layer in tests: routers run through TestClient
# without a session cookie, so `current_user` returns a synthetic operator.
os.environ.setdefault("MT_GENIE_AUTH_DISABLED", "1")

# Repo root on sys.path so `from server.lib...` and `from server.routers...` both resolve
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
