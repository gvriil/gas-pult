"""Владелец 25.11 (новый проект для Алексея): «доверять папке» не сработало — человек не смог написать. Папка пульта
доверенная заранее (флаг в настройках Claude Code), автоответ повторяет нажатия, пока вопрос не исчезнет, кнопка
«Да, доверяю» находит пункт и в узком окне."""
import json
import os
from pathlib import Path

from gas_pult import claude_trust, tmux

NARROW = """ Quick safety
 check: Is this a project
 you created or one you
 trust?
 Security guide
 ❯ No, exit
   Yes, I trust this
   folder
 Enter to confirm ·
 Esc to cancel"""


def cfg(tmp_path, data=None, mode=0o600):
    f = tmp_path / ".claude.json"
    f.write_text(json.dumps(data if data is not None else {"theme": "dark", "projects": {"/x": {"a": 1}}}))
    os.chmod(f, mode)
    return f


def test_project_folder_becomes_trusted_and_other_keys_stay(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    f = cfg(tmp_path)
    roots = [tmp_path / "projects"]
    folder = roots[0] / "tsrpa"
    folder.mkdir(parents=True)
    assert claude_trust.ensure(folder, roots, tmp_path) is True
    d = json.loads(f.read_text())
    assert d["projects"][str(folder)]["hasTrustDialogAccepted"] is True
    assert d["theme"] == "dark" and d["projects"]["/x"] == {"a": 1}         # чужие ключи на месте
    assert f.stat().st_mode & 0o777 == 0o600                               # права файла сохранены
    assert claude_trust.ensure(folder, roots, tmp_path) is True             # повтор — без записи, тот же итог


def test_never_trusts_root_home_or_outside(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    f = cfg(tmp_path)
    roots = [tmp_path / "projects"]
    for p in (roots[0], tmp_path, Path("/"), tmp_path / "elsewhere" / "x", roots[0] / ".." / "y"):
        assert claude_trust.ensure(p, roots, tmp_path) is False, p
    assert "hasTrustDialogAccepted" not in f.read_text()                   # согласие на корень — на всё внутри


def test_missing_or_broken_config_is_left_alone(tmp_path):
    roots = [tmp_path / "projects"]
    assert claude_trust.ensure(roots[0] / "a", roots, tmp_path) is False     # файла нет — не создаём
    (tmp_path / ".claude.json").write_text("{не json")
    assert claude_trust.ensure(roots[0] / "a", roots, tmp_path) is False
    assert (tmp_path / ".claude.json").read_text() == "{не json"


def test_narrow_window_question_still_recognised():
    assert tmux.trust_keys(NARROW) == ["Down", "Enter"]


class Lossy(tmux.Tmux):
    """Первые нажатия «теряются» (Claude Code ещё рисует экран): вопрос остаётся, пока не придёт второй ответ."""

    def __init__(self):
        self.sent, self.answers = [], 0

    def screen(self, wid, n=25):
        return [] if self.answers >= 2 else NARROW.splitlines()

    def run(self, *a):
        self.sent.append(a[-1])
        if a[-1] == "Enter":
            self.answers += 1
        return ""


def test_auto_answer_retries_until_question_is_gone():
    t = Lossy()
    assert t.accept_trust("@1", wait=5, step=0.01, settle=0.1) is True
    assert t.sent == ["Down", "Enter", "Down", "Enter"]                     # первая попытка потерялась — ответили снова


def test_button_finds_wrapped_option():
    from gas_pult.panel import sessions
    src = Path(sessions.__file__).read_text(encoding="utf-8")
    assert "target.startswith(c)" in src and 're.match(r"Yes, I trust", target, re.I)' in src
