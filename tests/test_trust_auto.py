"""Владелец и Алексей 20.11: «выбор 1/2/3 из терминала (доверие к папке) пользователь видеть не должен». Монитор
бота отвечает «Да» сам при любом пути запуска окна: новое, перезапуск, пробуждение, восстановление."""
from gas_pult import bot

SCREEN = """ Do you trust the files in this folder?

 /home/u/projects/shop

 ❯ 1. Yes, I trust this folder
   2. No, exit
"""


def pult():
    p = bot.Pult.__new__(bot.Pult)
    p.pressed, p.events = [], None
    p.tmux = type("T", (), {"keys": lambda self, wid, *k: p.pressed.append((wid, k))})()
    return p


def test_trust_question_answered_once_per_window():
    p = pult()
    w = {"id": "@4", "path": "/home/u/projects/shop"}
    assert p.trust_auto(w, SCREEN) is True and p.pressed == [("@4", ("Enter",))]
    assert p.trust_auto(w, SCREEN) is True and len(p.pressed) == 1       # тот же экран сразу — не жмём дважды
    assert p.trust_auto(w, "● готово\n❯ ") is False


def test_other_questions_are_not_answered():
    p = pult()
    ask = "Do you want to proceed?\n ❯ 1. Yes\n   2. No, and tell Claude what to do differently"
    assert p.trust_auto({"id": "@1"}, ask) is False and p.pressed == []   # разрешения — решение человека


# Claude Code 2.1.330 (снято 21.11 с настоящего окна): пункты без номеров, курсор — на «No, exit». Старый шаблон
# «❯ 1. Yes, I trust» не совпадал — вопрос 7 раз доходил до владельца (чат «Ущерб от затопления…»), Enter выбирал «нет».
NEW = """ Accessing workspace:
 /home/u
 Quick safety check: Is this a project you created or one you trust? (Like your own code, a
 well-known open source project, or work from your team). If not, take a moment to review what's in
 this folder first.
 Claude Code'll be able to read, edit, and execute files here.
 Security guide
 ❯ No, exit
   Yes, I trust this folder
 Enter to confirm · Esc to cancel
"""


def test_new_dialog_moves_to_yes_then_enter():
    from gas_pult import tmux
    assert tmux.trust_keys(NEW) == ["Down", "Enter"]                     # не Enter на «No, exit»
    assert tmux.trust_keys(SCREEN) == ["Enter"]                          # старый вид — как раньше
    on_yes = NEW.replace(" ❯ No, exit", "   No, exit").replace("   Yes, I trust", " ❯ Yes, I trust")
    assert tmux.trust_keys(on_yes) == ["Enter"]
    p = pult()
    assert p.trust_auto({"id": "@7", "path": "/home/u"}, NEW) is True
    assert p.pressed == [("@7", ("Down",)), ("@7", ("Enter",))]


def test_unclear_trust_screen_presses_nothing():
    from gas_pult import tmux
    assert tmux.trust_keys("Quick safety check: Is this a project you trust?\n(список ещё рисуется)") is None
    assert tmux.trust_keys("Do you want to proceed?\n ❯ 1. Yes\n   2. No") is None
