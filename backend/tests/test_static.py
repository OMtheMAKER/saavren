"""The API must serve the built UI wherever the package happens to sit."""
import os
from pathlib import Path

import pytest

import app.main as m


def test_web_dir_honours_the_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SAAVREN_WEB_DIR", str(tmp_path))
    assert m._web_dir() == tmp_path


def test_web_dir_always_ends_in_frontend_dist(monkeypatch):
    monkeypatch.delenv("SAAVREN_WEB_DIR", raising=False)
    found = m._web_dir()
    assert found.name == "dist"
    assert found.parent.name == "frontend"


def test_web_dir_finds_the_ui_from_a_deeper_package(monkeypatch, tmp_path):
    """The container layout copies backend/app to <root>/app, one level shallower
    than a checkout. A hardcoded ../../.. would miss it entirely."""
    monkeypatch.delenv("SAAVREN_WEB_DIR", raising=False)
    root = tmp_path / "root"
    web = root / "frontend" / "dist"
    web.mkdir(parents=True)
    pkg = root / "app"
    pkg.mkdir()
    here = pkg / "main.py"
    here.write_text("")

    real = Path(m.__file__).resolve()
    monkeypatch.setattr(m.Path, "__file__", str(here), raising=False)
    try:
        # _web_dir reads Path(__file__) from the module globals
        monkeypatch.setitem(m.__dict__, "__file__", str(here))
        assert m._web_dir() == web
    finally:
        monkeypatch.setitem(m.__dict__, "__file__", str(real))
