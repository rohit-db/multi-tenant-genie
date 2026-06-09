"""FastAPI application for Databricks App Template."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.routers import router


# Load environment variables from .env.local if it exists
def load_env_file(filepath: str) -> None:
  """Load environment variables from a file."""
  if Path(filepath).exists():
    with open(filepath) as f:
      for line in f:
        line = line.strip()
        if line and not line.startswith('#'):
          key, _, value = line.partition('=')
          if key and value:
            os.environ[key] = value


# Load .env files
load_env_file('.env')
load_env_file('.env.local')


@asynccontextmanager
async def lifespan(app: FastAPI):
  """Apply Lakebase migrations on startup if a database is configured.

  In Databricks Apps, the resource binding may not be present on the
  first deploy (the app has to exist before it can be bound). Log a
  warning and continue — the app serves UI + /health, and API calls
  that touch the DB will fail loudly until the binding lands.
  """
  import logging
  from pathlib import Path
  from server.lib import db

  has_db = bool(os.environ.get("PGHOST") or os.environ.get("DATABASE_URL"))
  mig_dir = Path(__file__).resolve().parent.parent / "sql" / "lakebase"

  if not has_db:
    logging.warning(
      "No PGHOST or DATABASE_URL set — skipping Lakebase migrations. "
      "Bind the database resource via the Apps UI to enable the metadata store."
    )
  elif mig_dir.exists() and any(mig_dir.glob("V*.sql")):
    try:
      db.apply_migrations(mig_dir)
    except Exception as e:
      logging.exception("Lakebase migrations failed (continuing): %s", e)
      # Don't raise — app should still serve UI + /health while DB issues
      # are sorted. API calls that touch DB will fail loudly until then.

  if has_db:
    try:
      from server.lib.auth import seed_demo_users
      seed_demo_users()
    except Exception as e:
      logging.warning("Demo user seeding skipped: %s", e)
  yield


app = FastAPI(
  title='Databricks App API',
  description='Modern FastAPI application template for Databricks Apps with React frontend',
  version='0.1.0',
  lifespan=lifespan,
)

app.add_middleware(
  CORSMiddleware,
  allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
  allow_credentials=True,
  allow_methods=['*'],
  allow_headers=['*'],
)

app.include_router(router, prefix='/api', tags=['api'])


@app.get('/health')
async def health():
  """Health check endpoint."""
  return {'status': 'healthy'}


# ============================================================================
# SERVE THE REACT SPA FROM web/build (MUST BE LAST!)
# ============================================================================
# We use react-router (BrowserRouter), so deep links like /login or /console
# must fall back to index.html. Built assets are served directly; everything
# else that isn't an /api or /health route returns index.html for the client
# router to resolve. These routes MUST be registered last.
_WEB_BUILD = Path(__file__).resolve().parent.parent / 'web' / 'build'
_INDEX = _WEB_BUILD / 'index.html'

if (_WEB_BUILD / 'assets').exists():
  app.mount('/assets', StaticFiles(directory=str(_WEB_BUILD / 'assets')), name='assets')

if _WEB_BUILD.exists():

  @app.get('/{full_path:path}')
  async def spa(full_path: str):
    """Serve a real built file when it exists, otherwise the SPA shell."""
    candidate = _WEB_BUILD / full_path
    if full_path and candidate.is_file():
      return FileResponse(str(candidate))
    return FileResponse(str(_INDEX))
