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
    # данные и настройки пульта — всегда во временной папке: тест не может задеть боевые people.json, ui.json,
    # prefs.json владельца (свой фикстур файла может поставить другую временную папку — он важнее)
    monkeypatch.setenv("GAS_PULT_DATA_DIR", os.path.join(d, "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", os.path.join(d, "cfg"))
    monkeypatch.setenv("GAS_PULT_CTX_DIR", os.path.join(d, "ctx"))   # снимки строки статуса — не боевые
    os.makedirs(os.path.join(d, "data"))
    yield
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def no_actor_leak():
    """«Кто действует» (``Pult.actor``) — общий для потока: тест бота, оставивший Telegram ID, ломал проверку страны
    в следующих тестах (порядок файлов менял итог). Сбрасываем до и после каждого теста."""
    from gas_pult.bot import Pult
    Pult.actor.uid = None
    yield
    Pult.actor.uid = None
