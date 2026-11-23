"""Shared fixtures: the demo systems on a free port and a hub config pointing at them."""
from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mock_systems  # noqa: E402
from integrationhub.config import load_config  # noqa: E402
from integrationhub.engine import Engine  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mock_url():
    port = _free_port()
    server = mock_systems.make_server(port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    yield url
    server.shutdown()
    server.server_close()


@pytest.fixture
def demo(mock_url):
    """Helper to drive the demo controls (outage, touch, new-customer)."""
    def call(action: str, **params):
        return requests.post(f"{mock_url}/__demo/{action}", params=params, timeout=5).json()
    return call


@pytest.fixture
def engine(tmp_path, mock_url, monkeypatch):
    for name, path in (("CRM_URL", "crm"), ("ERP_URL", "erp"), ("HELPDESK_URL", "helpdesk")):
        monkeypatch.setenv(name, f"{mock_url}/{path}")
    cfg_text = (ROOT / "hub.yaml").read_text(encoding="utf-8")
    cfg_text = cfg_text.replace("database: data/hub.db", "database: db/hub.db")
    cfg_path = tmp_path / "hub.yaml"
    cfg_path.write_text(cfg_text, encoding="utf-8")
    cfg = load_config(cfg_path)
    cfg.settings.retries = 0
    cfg.settings.timeout_seconds = 5
    return Engine(cfg)
