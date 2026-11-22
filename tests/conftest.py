"""Общее для всех тестов: tmux — только свой, по короткому сокету; боевой сервер владельца тесты не видят."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_default_tmux(monkeypatch):
    """Любой вызов tmux из кода пульта уходит на пустой сокет в /tmp (сервера там нет), а не в боевой `main`."""
    d = tempfile.mkdtemp(prefix="gp-", dir="/tmp")
    monkeypatch.setenv("GAS_PULT_TMUX_SOCKET", os.path.join(d, "none"))
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("GAS_PULT_STORAGE", raising=False)   # режим хранения — как в config.toml теста (json)
    # прогон всех тестов в другом режиме хранения (docs/STORAGE.md): GAS_PULT_TEST_STORAGE=dual|sqlite pytest …
    if (m := os.environ.get("GAS_PULT_TEST_STORAGE")):
        monkeypatch.setenv("GAS_PULT_STORAGE", m)
    # данные и настройки пульта — всегда во временной папке: тест не может задеть боевые people.json, ui.json,
    # prefs.json владельца (свой фикстур файла может поставить другую временную папку — он важнее)
    monkeypatch.setenv("GAS_PULT_DATA_DIR", os.path.join(d, "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", os.path.join(d, "cfg"))
    monkeypatch.setenv("GAS_PULT_CTX_DIR", os.path.join(d, "ctx"))   # снимки строки статуса — не боевые
    monkeypatch.setenv("GAS_PULT_DRIVE_ROOT", os.path.join(d, "drive"))   # Google Диск — не боевой ~/drive
    monkeypatch.setenv("GAS_PULT_PANEL_URL", "http://127.0.0.1:9")   # «Да» (approvals.py) — не у боевой панели
    monkeypatch.setenv("GAS_GUARD_LOG", os.path.join(d, "guard.jsonl"))   # журнал охранника Диска — не боевой
    os.makedirs(os.path.join(d, "data"))
    from gas_pult import alerts  # CI main (брифинг, бот) — без настоящего gh: тест подставит свой
    monkeypatch.setattr(alerts, "RUN", None)
    alerts._ci_cache.clear()
    yield
    shutil.rmtree(d, ignore_errors=True)


class Stored:
    """Данные служебного файла в любом режиме хранения (GAS_PULT_TEST_STORAGE): в sqlite JSON-файл не пишется, поэтому
    тесты смотрят то, что реально хранится, а не сам файл."""

    @staticmethod
    def load(path):
        from gas_pult import sqlstore, store
        return store.load(path, sqlstore.shape(Path(path).name))

    def text(self, path) -> str:
        import json
        return json.dumps(self.load(path), ensure_ascii=False)

    @staticmethod
    def save(path, d):
        from gas_pult import store
        with store.locked(path):
            store.save(path, d)

    @staticmethod
    def mode(path) -> int:
        """Права того, где лежат данные: JSON-файл или база SQLite."""
        from gas_pult import sqlstore
        path = Path(path)
        f = sqlstore.db_path(path.parent) if sqlstore.mode_for(path) == "sqlite" else path
        return f.stat().st_mode & 0o777


@pytest.fixture
def stored():
    return Stored()


@pytest.fixture(autouse=True)
def no_actor_leak():
    """«Кто действует» (``Pult.actor``) — общий для потока: тест бота, оставивший Telegram ID, ломал проверку страны
    в следующих тестах (порядок файлов менял итог). Сбрасываем до и после каждого теста."""
    from gas_pult.bot import Pult
    Pult.actor.uid = None
    yield
    Pult.actor.uid = None
