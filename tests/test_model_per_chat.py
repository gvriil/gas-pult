"""Модель и поставщик — только для этого чата (задача 37).

Было: «Модель» в панели слала ``/model <имя>`` в окно, а Claude Code сохраняет выбор в общие настройки
(``~/.claude/settings.json`` → ``"model"``) — модель менялась во всех сессиях; смена поставщика или «Перезапустить»
делали окно активным в боте — чат бота переключался на него. Теперь модель окна — перезапуском этого окна с
``--model`` (разговор продолжается), выбор запоминается на окно; общая модель по умолчанию — только отдельной
настройкой. Плюс: «у поставщика закончились деньги» (Z.ai 1113, DeepSeek 402) — распознать, показать, не предлагать час.
"""

import io
import json
import urllib.error

import pytest

from gas_pult import balance, humanize, models, webapp
from gas_pult.config import Config


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    p = webapp.Panel(Config(token="1:T", owners=[1], models=["opus", "sonnet", "haiku"]))
    state = {"active": "@2"}
    monkeypatch.setattr(p.pult, "state", lambda: dict(state))
    monkeypatch.setattr(p.pult, "set_state", lambda **kw: state.update(kw))
    opened, sent = [], []
    monkeypatch.setattr(p.tmux, "new_window",
                        lambda name, path, cmd, **kw: opened.append(cmd) or f"@{10 + len(opened)}")
    monkeypatch.setattr(p, "close", lambda w: "закрыто")
    monkeypatch.setattr(p, "slash", lambda w, cmd: sent.append(cmd) or [])
    monkeypatch.setattr(webapp.models, "command", lambda base, profile, st, **kw: f"claude [{profile or 'claude'}]")
    p.t = {"state": state, "opened": opened, "sent": sent}
    return p


def test_model_only_this_chat_without_slash_model(panel):
    w = {"id": "@1", "name": "a", "path": "/p/a", "profile": "zai", "mark": "zai"}
    d = panel.model(w, "haiku")
    assert d == {"id": "@11", "model": "haiku"}
    assert panel.t["opened"][-1] == "claude [zai] --model haiku --continue"   # тот же поставщик, разговор продолжается
    assert panel.t["sent"] == []                                             # /model (пишет в общие настройки) — нет
    st = panel.t["state"]
    assert st["window_models"] == {"@11": "haiku"}                           # выбор — только этого окна
    assert st["active"] == "@2"                                              # активная сессия бота не сменилась
    with pytest.raises(ValueError):
        panel.model(w, "")                                                   # меню /model — нет
    with pytest.raises(ValueError):
        panel.model(w, "haiku; rm -rf /")


def test_active_moves_only_with_the_same_chat(panel):
    w = {"id": "@2", "name": "b", "path": "/p/b", "profile": "claude"}
    panel.model(w, "opus")
    assert panel.t["state"]["active"] == "@11"                               # была активной — осталась (новое окно)


def test_provider_switch_drops_model_restart_keeps_it(panel):
    panel.t["state"]["window_models"] = {"@1": "haiku", "@5": "opus"}
    w = {"id": "@1", "name": "a", "path": "/p/a", "profile": "claude"}
    panel.restart(w, "claude")                                               # перезапуск тем же поставщиком
    assert panel.t["opened"][-1] == "claude [claude] --model haiku --continue"
    w2 = {"id": "@11", "name": "a", "path": "/p/a", "profile": "claude"}
    panel.restart(w2, "zai")                                                 # другой поставщик — его модель
    assert panel.t["opened"][-1] == "claude [zai] --continue"
    assert panel.t["state"]["window_models"] == {"@5": "opus"}               # чужое окно не тронуто


def test_revive_keeps_chat_model_and_bot_active(panel, monkeypatch):
    panel.t["state"]["window_models"] = {"@7": "sonnet"}
    respawned = []
    monkeypatch.setattr(panel.tmux, "window",
                        lambda wid: {"id": wid, "stopped": True, "mark": "claude", "path": "/p/c"})
    monkeypatch.setattr(panel.tmux, "respawn", lambda wid, path, cmd, mark="": respawned.append(cmd))
    monkeypatch.setattr(panel.pult, "home_of", lambda w: None)
    monkeypatch.setattr(panel, "need_claude", lambda: None)
    assert panel.revive("@7") == {"id": "@7"}
    assert respawned == ["claude [claude] --model sonnet --continue"]
    assert panel.t["state"]["active"] == "@2"


def test_default_model_is_explicit_setting(panel, monkeypatch, tmp_path):
    home = tmp_path / "claude"
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"model": "haiku", "theme": "dark", "hooks": {"x": 1}}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    assert panel.default_model() == {"model": "haiku", "models": ["opus", "sonnet", "haiku"]}
    panel.default_model("opus")
    d = json.loads((home / "settings.json").read_text())
    assert d == {"model": "opus", "theme": "dark", "hooks": {"x": 1}}         # остальное не тронуто
    panel.default_model("")
    assert "model" not in json.loads((home / "settings.json").read_text())
    with pytest.raises(ValueError):
        panel.default_model("glm")


def test_model_routes(panel, monkeypatch):
    assert "/api/model/default" in webapp.OWNER_ONLY and "/api/balance/clear" in webapp.OWNER_ONLY


# ---------- у поставщика закончились деньги ----------

ZAI = ('API Error: 429 {"error":{"code":"1113","message":"Insufficient balance or no resource package. '
       'Please recharge."}}')
DEEPSEEK = 'API Error: 402 {"error":{"message":"Insufficient Balance","type":"unknown_error"}}'
LIMIT = "API Error: 429 rate_limit_error: Too many requests"


def test_recognize_no_money():
    assert balance.seen(ZAI) and balance.seen(DEEPSEEK)
    assert not balance.seen(LIMIT) and not balance.seen("всё хорошо")
    assert humanize.error(ZAI)["key"] == "balance" and humanize.error(DEEPSEEK)["key"] == "balance"
    assert humanize.error(LIMIT)["key"] == "limit"                          # обычный лимит — по-прежнему лимит
    assert "закончились деньги" in humanize.error(ZAI)["ru"]


def test_mark_for_an_hour_and_clear():
    st = {}
    new = balance.mark(st, "zai", now=1000.0)
    assert new == {"zai": 1000.0} and balance.mark({"no_balance": new}, "zai", now=1500.0) is None
    st = {"no_balance": new}
    assert "zai" in balance.marked(st, now=1000.0 + balance.TTL - 1)
    assert "zai" not in balance.marked(st, now=1000.0 + balance.TTL + 1)     # через час — снова предлагаем
    assert balance.clear(st, "zai") == {}
    pub = {p["id"]: p for p in models.public({"no_balance": {"zai": __import__("time").time()}})}
    assert pub["zai"]["no_balance"] and not pub["deepseek"]["no_balance"]
    assert pub["zai"]["billing_url"].startswith("https://") and pub["claude"]["billing_url"] == ""


def test_deepseek_balance_check():
    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    assert balance.check("deepseek", "k", opener=lambda req, timeout: R(b'{"is_available": false}')) is False
    assert balance.check("deepseek", "k", opener=lambda req, timeout: R(b'{"is_available": true}')) is True

    def err(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 402, "Payment Required", {}, None)
    assert balance.check("deepseek", "k", opener=err) is False
    assert balance.check("zai", "k") is None                                 # у Z.ai бесплатной проверки нет


def test_session_card_and_mark_from_screen(panel):
    w = {"id": "@3", "profile": "zai"}
    assert panel.money_of(w, ["…", ZAI, "❯ "]) == {"no_balance": True}
    assert "zai" in panel.t["state"]["no_balance"]
    assert panel.money_of({"id": "@4", "profile": "claude"}, [ZAI]) == {}   # подписка Claude — свои сообщения
    assert panel.money_of({"id": "@5", "profile": "deepseek"}, [LIMIT]) == {}
