"""FastAPI application for Databricks App Template."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
# SERVE STATIC FILES FROM web/build (MUST BE LAST!)
# ============================================================================
# This static file mount MUST be the last route registered!
# It catches all unmatched requests and serves the React app.
# Any routes added after this will be unreachable!
_WEB_BUILD = Path(__file__).resolve().parent.parent / 'web' / 'build'
if _WEB_BUILD.exists():
  app.mount('/', StaticFiles(directory=str(_WEB_BUILD), html=True), name='static')
