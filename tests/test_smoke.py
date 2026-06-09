"""Baseline smoke test: the FastAPI app imports without error.

Used as a tripwire for the file-move tasks in this plan. After each move,
`pytest tests/test_smoke.py` should pass.
"""
import importlib


def test_app_imports():
    mod = importlib.import_module("server.app")
    assert mod.app is not None


def test_routers_import():
    importlib.import_module("server.routers")


def test_lib_imports():
    importlib.import_module("server.lib.config")
    importlib.import_module("server.primitives.sp_manager")
    importlib.import_module("server.primitives.genie")
    importlib.import_module("server.primitives.identity")
