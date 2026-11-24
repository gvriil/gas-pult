"""Экономия до сброса недельного лимита (владелец 24.11): неделя ≥ 70 % — чат на Opus перед ходом человека
переходит на Sonnet («/model sonnet» в чате, без перезапуска), один раз, с пометкой в ленте; закреплённую в пульте
модель, занятый чат, чат пространства и другие агенты — не трогаем."""
import json
import time
import types

from gas_pult import ctxsnap, teammsg
from gas_pult.botparts.windows import WindowsPart

SID = "0e80a522-eb39-4ed8-a4bb-40620386452e"


class Fake(WindowsPart):
    def __init__(self, tmp, screen="❯ "):
        self.st, self.slashes, self.scr = {}, [], screen
        self.cfg = types.SimpleNamespace(data=tmp)
        self.tmux = types.SimpleNamespace(screen=lambda wid, *a: [self.scr])

    def state(self):
        return dict(self.st)

    def set_state(self, **kw):
        self.st.update(kw)

    def run_slash(self, wid, cmd):
        self.slashes.append((wid, cmd))
        return []


def snap(ctx, used, model="Opus 5.5"):
    (ctx / f"{SID}.json").write_text(json.dumps({
        "model": {"id": "x", "display_name": model},
        "rate_limits": {"seven_day": {"used_percentage": used, "resets_at": time.time() + 86400}}}))


def test_switch_once_with_note(tmp_path, monkeypatch):
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    monkeypatch.setenv("GAS_PULT_CTX_DIR", str(ctx))
    snap(ctx, 73)
    f = Fake(tmp_path)
    w = {"id": "@3", "sid": SID, "mark": "claude"}
    assert f.economy_model(w) and f.slashes == [("@3", "/model sonnet")] and "@3" in f.st["window_econ"]
    note = teammsg.TeamMsgs(tmp_path / teammsg.FILE).all()[-1]
    assert note["w"] == "@3" and "Sonnet" in note["text"] and "73 %" in note["text"]
    assert not f.economy_model(w) and len(f.slashes) == 1                 # один раз


def test_no_switch_cases(tmp_path, monkeypatch):
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    monkeypatch.setenv("GAS_PULT_CTX_DIR", str(ctx))
    w = {"id": "@3", "sid": SID, "mark": "claude"}
    snap(ctx, 60)
    assert not Fake(tmp_path).economy_model(w)                          # неделя < 70 %
    snap(ctx, 80, "Sonnet 5.5")
    assert not Fake(tmp_path).economy_model(w)                          # уже не Opus
    snap(ctx, 80)
    f = Fake(tmp_path)
    f.st["window_models"] = {"@3": "opus"}
    assert not f.economy_model(w)                                       # Opus закреплён в пульте
    assert not Fake(tmp_path, "✻ Thinking… (esc to interrupt)").economy_model(w)   # занят
    assert not Fake(tmp_path).economy_model({**w, "space": "sp1"})      # пространство
    assert not Fake(tmp_path).economy_model({**w, "profile": "zai"})    # другой поставщик
    assert ctxsnap.day(0)[:2] in ctxsnap.DAYS
