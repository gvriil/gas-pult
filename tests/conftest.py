"""Общее для всех тестов: tmux — только свой, по короткому сокету; боевой сервер владельца тесты не видят."""

import os
import shutil
import tempfile

import pytest


@pytest.fixture(autouse=True)
def no_default_tmux(monkeypatch):
    """Любой вызов tmux из кода пульта уходит на пустой сокет в /tmp (сервера там нет), а не в боевой `main`."""
    d = tempfile.mkdtemp(prefix="gp-", dir="/tmp")
    monkeypatch.setenv("GAS_PULT_TMUX_SOCKET", os.path.join(d, "none"))
    monkeypatch.delenv("TMUX", raising=False)
    yield
    shutil.rmtree(d, ignore_errors=True)
