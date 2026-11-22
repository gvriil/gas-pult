"""Маршруты области «Команды и терминал» (MONOLITH-PLAN §3.2, шаг 7): вкладка «Команды» (журнал, вывод,
«Выполнить», «Готово», «В терминале»), окно терминала панели ``gp-term`` (экран, строка, клавиша, закрыть), живой
терминал (история, текст, клавиши, размер — задача 50), «Выполнить» из ответа агента.

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Права (``access.py``: ``OWNER_ONLY``, ``TERM``, ``TTY`` и режим разработчика ``H.dev_tty``, код
подтверждения нового входа ``CONFIRM``) проверены до вызова — ``H.permit``; фокус-ссылка — ``H.focus_call``
(``FOCUS_POST`` и окно ссылки). Живой терминал — развилка ``POST_P``; «Выполнить» из ответа — ``POST_W`` (ветки шли
после ``w = self.win(b.get("w"))``). Выполняют команды ``Panel`` (``panel/work.py``) и ``termwin``. Остались в
цепочке: «Рабочий стол» (``/api/desktop/*``), «Терминал» ``/api/shell/open`` и ``/api/links/prefs`` — им нужны
``desktop_up``, ``desktop_tab``, ``desk_*``, ``shell_window``, ``link_pref*`` верхнего уровня ``webapp`` (тесты
подменяют их там); ``/api/gate/desktop`` — до входа, в ``do_GET``. Таблицы и подписи — ``routes/__init__.py``.
"""

from gas_pult import termwin


def commands_list(self, q: dict):
    """GET /api/commands"""
    panel = self.panel
    return panel.command_log(self.who()[1] == "owner")


def commands_output(self, q: dict):
    """GET /api/commands/output"""
    panel = self.panel
    out = panel.journal.output(q.get("id", ""))
    if out is None:
        raise LookupError("вывода этой команды уже нет")
    return {"out": out}


def term_screen(self, q: dict):
    """GET /api/term — окно терминала панели: что на экране, живо ли"""
    panel = self.panel
    return termwin.screen(panel.tmux, q.get("id", ""))


def tty_history(self, q: dict):
    """GET /api/tty — живой терминал: история окна страницами (задача 50)"""
    panel = self.panel
    w = panel.tty_window(str(q.get("w") or ""), self.who()[1] == "owner", write=False, space=self.space())
    d = termwin.history(panel.tmux, w["id"], q.get("start"), q.get("end"), q.get("all") == "1",
                        q.get("color") == "1")             # color — экран для xterm.js (добавлено)
    return {**d, "w": w["id"], "name": w.get("name", ""), "kind": panel.tty_kind(w),
            "path": w.get("path", ""), "login": self.login_of(w, d.get("lines") or [])}   # низ — экран


def commands_run(self, b: dict):
    """POST /api/commands/run"""
    panel = self.panel
    return panel.command_run(str(b.get("id", "")), bool(b.get("confirmed")))


def commands_mark(self, b: dict):
    """POST /api/commands/mark"""
    panel = self.panel
    return panel.command_mark(str(b.get("id", "")), b.get("done", True) is not False)


def commands_term(self, b: dict):
    """POST /api/commands/term — вкладка «Команды»: нужен ввод — в окне терминала"""
    panel = self.panel
    return panel.command_term(str(b.get("id", "")), bool(b.get("confirmed")))


def term_type(self, b: dict):
    """POST /api/term/type — строка (пароль) — в окно gp-term; из Mini App — нет"""
    panel = self.panel
    if self.headers.get("X-Telegram-Init-Data"):
        raise ValueError("пароль в Telegram не вводим — откройте панель в браузере или Termius")
    termwin.type_line(panel.tmux, str(b.get("id", "")), str(b.get("text", "")))
    return {"ok": True}


def term_key(self, b: dict):
    """POST /api/term/key — Ctrl+C, Ctrl+D, Enter"""
    panel = self.panel
    termwin.key(panel.tmux, str(b.get("id", "")), str(b.get("key", "")))
    return {"ok": True}


def term_close(self, b: dict):
    """POST /api/term/close"""
    panel = self.panel
    termwin.close(panel.tmux, str(b.get("id", "")))
    return {"ok": True}


def tty_input(self, path: str, b: dict):
    """POST_P /api/tty/type|key|size — живой терминал: текст, клавиши, размер"""
    panel = self.panel
    owner = self.who()[1] == "owner"
    w = panel.tty_window(str(b.get("w") or ""), owner, write=True, space=self.space())
    if path == "/api/tty/size":                    # окно tmux — под размер области терминала (17.11)
        return termwin.tty_size(panel.tmux, w["id"], b.get("cols"), b.get("rows"), bool(b.get("reset")))
    if path == "/api/tty/key":
        termwin.tty_key(panel.tmux, w["id"], str(b.get("key", "")), owner)
        return {"ok": True}
    if w.get("name") == termwin.WINDOW and self.headers.get("X-Telegram-Init-Data"):
        raise ValueError("в окно с паролем из Telegram не вводим — откройте панель в браузере")
    termwin.tty_type(panel.tmux, w["id"], str(b.get("text", "")))
    panel.pult.deliv.record(w["id"], "tty", str(b.get("text", "")), res="typed")   # без Enter, без текста
    return {"ok": True}


def run(self, b: dict, w: dict):
    """POST_W /api/run"""
    panel = self.panel
    return panel.run(w, int(b.get("i", -1)), str(b.get("sha", "")), bool(b.get("confirmed")))


def run_term(self, b: dict, w: dict):
    """POST_W /api/run/term — из ответа: нужен ввод — в окне терминала, не вслепую"""
    panel = self.panel
    return panel.term_run(w, int(b.get("i", -1)), str(b.get("sha", "")), bool(b.get("confirmed")))


GET = {"/api/commands": commands_list, "/api/commands/output": commands_output, "/api/term": term_screen,
       "/api/tty": tty_history}
POST = {"/api/commands/run": commands_run, "/api/commands/mark": commands_mark, "/api/commands/term": commands_term,
        "/api/term/type": term_type, "/api/term/key": term_key, "/api/term/close": term_close}
POST_P = {("/api/tty/type", "/api/tty/key", "/api/tty/size"): tty_input}
POST_W = {"/api/run": run, "/api/run/term": run_term}
