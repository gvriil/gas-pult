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
