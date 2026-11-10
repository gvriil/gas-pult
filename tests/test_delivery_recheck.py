"""Доставка в окно: журнал ``sends.jsonl``, перепроверка через 3/10/30 с, сторож черновиков, кнопка «Отправить».

Регрессия 10.11: ответ владельца с ночи висел неотправленным в поле ввода окна, а пульт считал его доставленным.
Причина (а), воспроизведена на подставном экране (``tests/fake_cc.py``): «❯» Claude Code ставит не только в поле
ввода, но и у выбранной строки панели фоновых агентов под ним («❯● main») — ``prompt_draft`` брал последнюю «❯»
на экране, видел там «● main», решал «в поле не наш текст — ушло» и повторный Enter не жал. Причина (б): когда фокус
в панели агентов, Enter уходит туда, а текст остаётся в поле (бледным); бледный текст считался подсказкой.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from gas_pult import activity, bot, deliveries, tmux, webapp

TEXT = "Полоса — проекты, вход только владельцу, «Выполнить» из фокуса убрать"
RULE = "\x1b[38;5;244m" + "─" * 60 + "\x1b[39m"
STATUS = ["  \x1b[38;5;246m⏵⏵ accept edits on (shift+tab to cycle)\x1b[39m", "  gas-pult · main",
          "  3 background tasks"]


def field(text: str, style: str = "\x1b[38;5;246m") -> list[str]:
    return ["● Готово.", "", RULE, f"❯ {style}{text}\x1b[39m\x1b[7m \x1b[27m", RULE, *STATUS]


# ---------- (а) поле ввода — не последняя «❯» на экране ----------

def test_agent_panel_pointer_below_is_not_the_field():
    lines = [*field(TEXT), "❯● main  ход", " ◯ general-purpose  Исследует"]
    assert tmux.prompt_draft(lines) == TEXT


def test_file_suggestions_below_are_not_the_field():
    lines = ["", RULE, "❯ что делает @src/au", RULE, "  ❯ src/auth.ts", "    src/auth.test.ts"]
    assert tmux.prompt_draft(lines) == "что делает @src/au"


def test_quoted_text_in_grey_is_a_draft():
    assert tmux.prompt_draft(field("«Выполнить» — убрать")) == "«Выполнить» — убрать"


def test_dim_field_is_a_draft_only_when_asked():
    lines = [*field(TEXT, "\x1b[2m"), "❯● main"]
    assert tmux.prompt_draft(lines) == ""                   # для «не потерять черновик» — как раньше, подсказка
    assert tmux.prompt_draft(lines, dim=True) == TEXT       # для «наш текст висит?» — видим


def test_placeholder_after_cursor_is_not_a_draft():
    lines = ["", RULE, "❯ \x1b[7m \x1b[27m\x1b[2mTry \"fix lint errors\"\x1b[22m", RULE]
    assert tmux.prompt_draft(lines) == ""


def test_sent_message_above_and_empty_field():
    lines = ["\x1b[48;5;237m❯ " + TEXT + "\x1b[49m", "● got it", "", RULE, "❯ \x1b[7m \x1b[27m", RULE, "❯● main"]
    assert tmux.prompt_draft(lines, dim=True) == ""


def test_wrapped_long_draft_continues_to_bottom_rule():
    lines = ["", RULE, "❯ первая часть длинного", "  ответа владельцу", RULE, "❯● main"]
    assert tmux.prompt_draft(lines) == "первая часть длинного\nответа владельцу"


# ---------- журнал доставок ----------

def test_log_has_no_text_and_is_private(tmp_path):
    log = deliveries.Log(tmp_path / "sends.jsonl")
    log.record("@5", "panel", TEXT, res="sent", after="empty")
    raw = (tmp_path / "sends.jsonl").read_text()
    assert "Полоса" not in raw and "фокуса" not in raw
    rec = json.loads(raw)
    assert rec["w"] == "@5" and rec["src"] == "panel" and rec["len"] == len(TEXT) and len(rec["sha"]) == 12
    assert rec["res"] == "sent" and rec["after"] == "empty"
    assert os.stat(tmp_path / "sends.jsonl").st_mode & 0o777 == 0o600


def test_log_rotates(tmp_path, monkeypatch):
    monkeypatch.setattr(deliveries, "SLACK", 5)
    log = deliveries.Log(tmp_path / "s.jsonl", keep=10)
    for i in range(40):
        log.record("@1", "bot", f"текст {i}", res="sent")
    n = len((tmp_path / "s.jsonl").read_text().splitlines())
    assert 10 <= n <= 15


def test_match_by_head_wrapped_or_cut(tmp_path):
    log = deliveries.Log(tmp_path / "s.jsonl")
    long = TEXT + " " + "ещё много слов " * 20
    log.record("@5", "panel", long, res="sent")
    assert log.match("@5", TEXT.replace(", ", ",\n"))          # перенос строк в поле ввода — тот же текст
    assert log.match("@5", TEXT[:30]) is None                  # короче 40 знаков от длинного — не узнаём
    assert log.match("@6", TEXT) is None                       # другое окно
    assert log.match("@5", "человек печатает своё") is None
    log.record("@5", "panel", "да", res="sent")
    assert log.match("@5", "да")["len"] == 2


# ---------- перепроверка и сторож ----------

class Win:
    """Окно с подставным полем ввода: черновики — по очереди, экран — занят или свободен."""

    def __init__(self, drafts, screens=None):
        self.drafts, self.screens, self.keys_sent = list(drafts), list(screens or []), []

    def draft(self, wid, dim=False):
        return self.drafts.pop(0) if self.drafts else ""

    def screen(self, wid, n=25):
        return [self.screens.pop(0) if self.screens else "❯ "]

    def keys(self, wid, *k):
        self.keys_sent.append(k)

    def window(self, wid):
        return {"id": wid, "cmd": "claude", "name": "gas-pult"}


@pytest.fixture
def pult(tmp_path):
    p = bot.Pult.__new__(bot.Pult)
    p.locks, p.actor = tmp_path / "locks", type("A", (), {})()
    p.deliv = deliveries.Log(tmp_path / "sends.jsonl")
    p.sends = activity.Sends()
    p.drafts = {}
    p.said = []
    p.broadcast = lambda text, **kw: p.said.append((text, kw))
    return p


def last(p):
    return [json.loads(x) for x in p.deliv.path.read_text().splitlines()][-1]


def test_recheck_presses_enter_when_text_left(pult):
    pult.tmux = Win([TEXT, ""])                               # 3 с: висит → Enter; 10 с: ушёл
    assert pult.recheck({"id": "@5"}, TEXT, "panel", sleep=lambda s: None) == "gone"
    assert pult.tmux.keys_sent == [("Enter",)]
    assert last(pult)["res"] == "redelivered" and last(pult)["src"] == "panel" and not pult.said


def test_recheck_waits_while_busy(pult):
    pult.tmux = Win([TEXT, ""], ["✶ Работает… (esc to interrupt)"])
    assert pult.recheck({"id": "@5"}, TEXT, sleep=lambda s: None) == "gone"
    assert pult.tmux.keys_sent == []                          # в занятое окно Enter не жмём


def test_recheck_stuck_marks_and_notifies_once(pult):
    pult.tmux = Win([TEXT] * 3)
    pult.sends.sent("@5", TEXT)
    pult.sends.delivered("@5")
    assert pult.recheck({"id": "@5", "name": "gas-pult"}, TEXT, "panel", sleep=lambda s: None) == "unsent"
    assert len(pult.tmux.keys_sent) == 2                     # 3 и 10 с; на 30 с — уже не вслепую, а владельцу
    assert last(pult)["res"] == "unsent"
    text, kw = pult.said[0]
    assert "не отправлено" in text and "Полоса" not in text
    btn = kw["reply_markup"]["inline_keyboard"][0][0]
    assert btn["callback_data"] == f"rs:@5:{deliveries.sha(TEXT)}" and "Отправить" in btn["text"]
    st = activity.combine({}, pult.sends.get("@5"), {})
    assert st["phase"] == "unsent" and st["action"] == "enter" and "Не отправлено" in st["text"]
    pult.tmux = Win([TEXT] * 3)
    pult.recheck({"id": "@5"}, TEXT, sleep=lambda s: None)
    assert len(pult.said) == 1                                # об одном тексте — один раз


def test_recheck_dialog_not_pressed(pult):
    pult.tmux = Win([TEXT] * 3, ["Do you want to proceed?"] * 3)
    assert pult.recheck({"id": "@5"}, TEXT, sleep=lambda s: None) == "unsent"
    assert pult.tmux.keys_sent == []


def test_recheck_leaves_someone_elses_draft(pult):
    pult.tmux = Win(["человек печатает своё"])
    assert pult.recheck({"id": "@5"}, TEXT, sleep=lambda s: None) == "gone"
    assert pult.tmux.keys_sent == [] and not pult.said


def test_draft_watch_after_two_minutes(pult):
    pult.deliv.record("@5", "panel", TEXT, res="sent", after="empty")
    lines = [*field(TEXT), "❯● main"]
    w = {"id": "@5", "name": "gas-pult"}
    assert not pult.draft_watch(w, lines, now=1000)
    assert not pult.draft_watch(w, lines, now=1100)
    assert pult.draft_watch(w, lines, now=1121)
    assert not pult.draft_watch(w, lines, now=1200)           # один раз на текст
    assert "не отправлено" in pult.said[0][0] and last(pult)["src"] == "watch"


def test_draft_watch_ignores_foreign_and_busy(pult):
    pult.deliv.record("@5", "panel", TEXT, res="sent")
    w = {"id": "@5", "name": "x"}
    other = field("человек печатает в Termius")
    for t in (0, 200, 400):
        assert not pult.draft_watch(w, other, now=t)
    busy = [*field(TEXT), "✶ Работает… (esc to interrupt)"]
    for t in (0, 200, 400):
        assert not pult.draft_watch(w, busy, now=t)
    assert not pult.said


def test_push_enter_checks_text(pult):
    pult.deliv.record("@5", "panel", TEXT, res="sent")
    pult.tmux = Win([TEXT, ""])
    assert "Отправлено" in pult.push_enter("@5", deliveries.sha(TEXT), sleep=lambda s: None)
    assert pult.tmux.keys_sent == [("Enter",)]
    pult.tmux = Win(["своё"])
    assert "нет этого текста" in pult.push_enter("@5", sleep=lambda s: None)
    pult.tmux = Win([TEXT], ["Do you want to proceed?"])
    assert "вопрос" in pult.push_enter("@5", sleep=lambda s: None) and pult.tmux.keys_sent == []


def test_to_claude_logs_source_and_result(pult, monkeypatch):
    class T:
        last_paste = tmux.Tmux.last_paste

        def paste(self, wid, text):
            self.last_paste.r = {"ok": True, "result": "retried 1", "after": "empty"}
            return True
    pult.tmux = T()
    monkeypatch.setattr(pult, "cost_paused", lambda wid: False, raising=False)
    monkeypatch.setattr(pult, "ready_for_text", lambda wid: None, raising=False)
    monkeypatch.setattr(bot.Pult, "RECHECK", ())
    pult.to_claude({"id": "@5", "profile": "claude"}, TEXT, src="focus")
    r = last(pult)
    assert (r["src"], r["res"], r["after"], r["len"]) == ("focus", "retried 1", "empty", len(TEXT))


def test_resend_allowed_where_send_is():
    assert "/api/resend" in webapp.FOCUS_POST and "/api/resend" in webapp.SPACE_OK


# ---------- подставной экран в своём tmux: старый разбор считал «ушло», новый — нет ----------

FAKE = Path(__file__).with_name("fake_cc.py")


@pytest.fixture
def fake_window():
    if not shutil.which("tmux"):
        pytest.skip("нужен tmux")
    d = tempfile.mkdtemp(prefix="gp-", dir="/tmp")
    sock, ctl, log = (os.path.join(d, x) for x in ("s", "ctl", "log"))
    assert len(sock) < 100

    def start(mode):
        Path(ctl).write_text(mode + "\n")
        subprocess.run(["tmux", "-S", sock, "new-session", "-d", "-s", "t", "-x", "100", "-y", "24",
                        f"env FAKE_CC_CTL={ctl} FAKE_CC_LOG={log} {sys.executable} {FAKE}"], check=True)
        t = tmux.Tmux("t", socket=sock)
        end = time.time() + 5
        while time.time() < end and "fake Claude" not in "\n".join(t.screen(t.windows()[0]["id"])):
            time.sleep(0.1)
        return t, t.windows()[0]["id"], Path(ctl), Path(log)
    yield start
    subprocess.run(["tmux", "-S", sock, "kill-server"], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


def test_fake_screen_panel_focus_is_reported_stuck(fake_window):
    t, wid, _, log = fake_window("panel")
    r = t.paste_ex(wid, TEXT)
    assert r == {"ok": False, "result": "stuck", "after": "ours"}       # было: True — «доставлено»
    assert t.draft(wid, dim=True) == TEXT and not log.exists()


def test_fake_screen_lost_enter_then_recheck_delivers(fake_window, tmp_path):
    t, wid, ctl, log = fake_window("panel")
    t.paste_ex(wid, TEXT, sleep=lambda s: time.sleep(min(s, 0.3)))
    ctl.write_text("normal\n")                              # фокус вернулся в поле ввода
    p = bot.Pult.__new__(bot.Pult)
    p.locks, p.tmux = tmp_path / "locks", t
    p.deliv, p.sends, p.said = deliveries.Log(tmp_path / "s.jsonl"), activity.Sends(), []
    p.broadcast = lambda text, **kw: p.said.append(text)
    assert p.recheck({"id": wid}, TEXT, "panel", sleep=lambda s: time.sleep(0.3)) == "gone"
    assert log.read_text().strip() == TEXT and not p.said


def test_fake_screen_first_enter_dropped_is_retried(fake_window):
    t, wid, _, log = fake_window("drop1")
    r = t.paste_ex(wid, TEXT)
    assert r["ok"] and r["result"] == "retried 1" and log.read_text().strip() == TEXT
