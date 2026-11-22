"""Автовход коннекторов, фаза 2 (GAS-49; docs/CONNECTORS.md, «Автовход»): нажать «Разрешить» в Chrome агента.

Коннектор потерял вход (needs_auth) → программа harness выдаёт адрес входа (``claude mcp login <имя> --no-browser``,
``pi mcp login``, ``opencode mcp auth`` — таблица в docs) и ждёт возврата на свой адрес ``localhost``. Мы открываем
этот адрес вкладкой в Chrome агента (DevTools ``127.0.0.1:9222``, тот же «Браузер» стола, что видит владелец) и
смотрим, что за страница:

- **согласие** («Allow», «Authorize», «Разрешить»…) — снимаем отпечаток: домен + права (``scope`` из адреса) + видимый
  список прав. Нажимаем, **только если** отпечаток совпал с тем, что владелец уже разрешал для этого коннектора.
  Отпечатка нет (первый раз) или права другие — не нажимаем: вкладка остаётся открытой, задача «Ждут вас»; после
  ручного успеха отпечаток запоминает ``connwatch.Watch`` (``connwatch_state.json``, ``approved``);
- **пароль** — подставляем логин и пароль из ``connectors.kdbx``, только если домен в ``PASSWORD_SERVICES`` (сверены
  условия сервиса; пока пусто) и запись есть. Google и Telegram — никогда (``NEVER_PASSWORD``);
- **2FA, капча, неизвестная страница** — не обходим: «Ждут вас», вкладка остаётся с тем, что уже заполнено.

Значение пароля уходит только в DevTools (``Input.insertText``) — не в журнал, события, задачи и вывод. Адреса в
причинах — без query (там коды и state). Только стандартная библиотека; WebSocket — ``deskmobile.Conn``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from gas_pult import config, connwatch

CDP = "http://127.0.0.1:9222"      # Chrome агента; GAS_PULT_CDP — другой адрес (тесты ставят пустой порт)
HOLD = 3600              # с: столько программа входа ждёт возврата (владелец может нажать «Разрешить» позже)
URL_WAIT = 60            # с: ждать адрес входа от программы
PAGE_WAIT = 25           # с: ждать, пока страница входа станет понятной (переадресации, загрузка)
AFTER_CLICK = 90         # с: после нажатия — ждать завершения программы входа

# Вход по паролю — только сюда: домен → адрес условий сервиса (проверено человеком, что автоматический вход
# не запрещён). Пока не проверен ни один сервис — пусто.
PASSWORD_SERVICES: dict[str, str] = {}
# Пароль сюда не вводится никогда (решение владельца): вход в Google и Telegram — только живой человек.
NEVER_PASSWORD = ("google.com", "gmail.com", "googleusercontent.com", "youtube.com", "telegram.org", "telegram.me",
                  "t.me")

LOGIN = {   # harness → команда входа; адрес входа программа печатает сама
    "claude": ["claude", "mcp", "login", "{name}", "--no-browser"],
    "pi": ["pi", "mcp", "login", "{name}", "--timeout", str(HOLD)],
    "opencode": ["opencode", "mcp", "auth", "{name}"],
}

ALLOW = re.compile(r"^\s*(allow( access)?|authori[sz]e|approve|accept|grant( access)?|разрешить( доступ)?|"
                   r"предоставить доступ|авторизовать|принять)\s*$", re.I)
DENY = re.compile(r"deny|cancel|reject|decline|отмен|отклон|запрет", re.I)
TWOFA = re.compile(r"two.?factor|2.?step|verification code|authenticator app|security key|passkey|"
                   r"one.?time (pass)?code|двухэтап|двухфактор|код подтверждения|код из (sms|смс|приложения)", re.I)
_URL = re.compile(r"https?://[^\s\x1b\"'<>]+")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


class Fail(Exception):
    """Автовход не удался по технической причине (не «нужен человек»)."""


# ---------- адреса без секретов ----------
def host(url: str) -> str:
    return (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()


def bare(url: str) -> str:
    """Адрес без query и фрагмента — для причин и событий (в query бывают code и state)."""
    u = urllib.parse.urlsplit(str(url or ""))
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", "")) if u.scheme else ""


def scrub(text: str) -> str:
    """Все адреса в тексте — без query."""
    return _URL.sub(lambda m: bare(m.group(0)), str(text or ""))


def domain_in(h: str, domains) -> bool:
    h = (h or "").lower().rstrip(".")
    return any(h == d or h.endswith("." + d) for d in domains)


def loopback(url: str) -> bool:
    return host(url) in ("localhost", "127.0.0.1", "::1")


# ---------- отпечаток согласия ----------
def scopes(*urls) -> list[str]:
    out = set()
    for u in urls:
        for v in urllib.parse.parse_qs(urllib.parse.urlsplit(str(u or "")).query).get("scope", []):
            out.update(x for x in re.split(r"[\s,+]+", v) if x)
    return sorted(out)


def fingerprint(page_url: str, auth_url: str, perms) -> dict:
    """Домен страницы согласия + права из адреса + видимый список прав (текст хранится только хэшем)."""
    norm = sorted({" ".join(str(p).split()).lower()[:200] for p in perms or [] if str(p).strip()})[:40]
    d = {"host": host(page_url), "scope": scopes(auth_url, page_url),
         "perms": hashlib.sha256(json.dumps(norm, ensure_ascii=False).encode()).hexdigest()[:16]}
    d["fp"] = hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:24]
    return d


# ---------- что за страница ----------
SNAP_JS = r"""(() => {
 const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
   return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
 const t = e => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 80);
 const id = i => ((i.name || '') + ' ' + (i.id || '') + ' ' + (i.autocomplete || '')).toLowerCase();
 const btns = [...document.querySelectorAll('button,input[type=submit],input[type=button],[role=button]')]
   .filter(vis).map(t).filter(Boolean).slice(0, 40);
 const ins = [...document.querySelectorAll('input')].filter(vis);
 return JSON.stringify({url: location.href, ready: document.readyState, btns,
  pw: ins.some(i => i.type === 'password'),
  otp: ins.some(i => i.autocomplete === 'one-time-code' || /otp|totp|2fa|mfa|one.?time|verif/.test(id(i))),
  user: ins.some(i => ['email', 'text', 'tel'].includes(i.type) && /user|login|email|account/.test(id(i))),
  captcha: !!document.querySelector('iframe[src*="captcha"],iframe[src*="challenges.cloudflare"],.g-recaptcha,' +
    '.h-captcha,.cf-turnstile,[class*=captcha],[id*=captcha]'),
  perms: [...document.querySelectorAll('li')].filter(vis).map(e => e.innerText.trim().replace(/\s+/g, ' ')
    .slice(0, 200)).filter(Boolean).slice(0, 40),
  text: (document.body && document.body.innerText || '').slice(0, 3000)});
})()"""


def kind(s: dict) -> str:
    """callback · captcha · twofa · password · consent · unknown."""
    if loopback(s.get("url", "")):
        return "callback"
    if s.get("captcha"):
        return "captcha"
    if s.get("otp") or (not s.get("pw") and TWOFA.search(s.get("text") or "")):
        return "twofa"
    if s.get("pw"):
        return "password"
    if allow_buttons(s):
        return "consent"
    return "unknown"


def allow_buttons(s: dict) -> list[str]:
    return [b for b in s.get("btns") or [] if ALLOW.match(b) and not DENY.search(b)]


# ---------- Chrome агента ----------
class Browser:
    """Одна вкладка Chrome агента через DevTools. ``http`` и ``connect`` тесты подменяют (без настоящего Chrome)."""

    def __init__(self, cdp: str | None = None, http=None, connect=None):
        from gas_pult import deskmobile

        self.cdp = (cdp or os.environ.get("GAS_PULT_CDP") or CDP).rstrip("/")
        self.http = http or self._http
        self.connect = connect or deskmobile.Conn
        self.tab, self.c = None, None

    def _http(self, path: str, method: str = "GET"):
        req = urllib.request.Request(self.cdp + path, method=method)
        try:
            with urllib.request.urlopen(req, timeout=4) as r:
                body = r.read()
        except OSError as e:
            raise Fail(f"браузер агента не ответил (DevTools): {type(e).__name__}") from None
        try:
            return json.loads(body or b"null")
        except ValueError:
            return body.decode("utf-8", "replace")            # /json/activate отвечает текстом

    def alive(self) -> bool:
        try:
            return isinstance(self.http("/json/version"), dict)
        except Fail:
            return False

    def open(self, url: str):
        t = self.http("/json/new?" + urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%-._~"), method="PUT")
        if not isinstance(t, dict) or not t.get("webSocketDebuggerUrl"):
            raise Fail("браузер агента не открыл вкладку")
        self.tab = t
        self.http("/json/activate/" + str(t.get("id")))
        self.c = self.connect(t["webSocketDebuggerUrl"])

    def eval(self, expr: str):
        r = self.c.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return (r.get("result") or {}).get("value")

    def snap(self) -> dict:
        try:
            return json.loads(self.eval(SNAP_JS) or "{}")
        except ValueError:
            return {}

    def click(self, label: str) -> bool:
        """Настоящий щелчок (``Input.dispatchMouseEvent``) по видимой кнопке с этой надписью."""
        js = ("(() => { const L = " + json.dumps(label) + "; const e = [...document.querySelectorAll('button,"
              "input[type=submit],input[type=button],[role=button]')].find(e => (e.innerText || e.value || "
              "e.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 80) === L); if (!e) "
              "return null; e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); "
              "return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        xy = self.eval(js)
        if not (isinstance(xy, list) and len(xy) == 2):
            return False
        for typ in ("mousePressed", "mouseReleased"):
            self.c.call("Input.dispatchMouseEvent", type=typ, x=xy[0], y=xy[1], button="left", clickCount=1)
        return True

    def fill(self, selector_js: str, value: str) -> bool:
        """Поле в фокус — и текст через ``Input.insertText``. Значение никуда больше не пишется."""
        ok = self.eval(f"(() => {{ const e = {selector_js}; if (!e) return false; e.focus(); e.select && e.select();"
                       " return true; })()")
        if ok:
            self.c.call("Input.insertText", text=value)
        return bool(ok)

    def enter(self):
        for typ in ("keyDown", "keyUp"):
            self.c.call("Input.dispatchKeyEvent", type=typ, key="Enter", code="Enter", windowsVirtualKeyCode=13,
                        **({"text": "\r"} if typ == "keyDown" else {}))

    def detach(self):
        """Отключиться от вкладки, вкладку не закрывать (её видит и может дожать человек)."""
        if self.c:
            self.c.close()
            self.c = None


USER_JS = ("[...document.querySelectorAll('input')].find(i => ['email','text','tel'].includes(i.type) && "
           "/user|login|email|account/i.test((i.name||'')+' '+(i.id||'')+' '+(i.autocomplete||'')))")
PASS_JS = "document.querySelector('input[type=password]')"


# ---------- программа входа ----------
HOLD_PY = r"""
import fcntl, os, pty, select, signal, struct, sys, termios, time
secs, out, cmd = float(sys.argv[1]), sys.argv[2], sys.argv[3:]
pid, fd = pty.fork()
if pid == 0:
    os.execvp(cmd[0], cmd)
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 4000, 0, 0))
f = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
end, code = time.monotonic() + secs, None
while time.monotonic() < end and code is None:
    if select.select([fd], [], [], 1)[0]:
        try:
            data = os.read(fd, 65536)
        except OSError:
            data = b""
        if data:
            os.write(f, data)
    p, st = os.waitpid(pid, os.WNOHANG)
    if p:
        code = os.waitstatus_to_exitcode(st)
if code is None:
    os.kill(pid, signal.SIGTERM)
    code = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
os.write(f, ("\n[gas-pult exit %d]\n" % code).encode())
"""
_EXIT = re.compile(r"\[gas-pult exit (-?\d+)\]")


class Login:
    """Программа входа harness в своём терминале (pty: ``claude mcp login`` без терминала сразу сдаётся). Живёт
    отдельно от сторожа до ``HOLD`` секунд — владелец успеет нажать «Разрешить» сам. Вывод — в файл 0600 в
    ``<данные>/relogin/`` (там адрес входа с state; кодов нет — код приходит на localhost программе)."""

    def __init__(self, c: dict, data: Path | None = None, popen=subprocess.Popen, clock=time.monotonic,
                 sleep=time.sleep):
        cmd = [x.replace("{name}", c["name"]) for x in LOGIN[c["harness"]]]
        d = Path(data or config.data_dir()) / "relogin"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        (d / "bin").mkdir(exist_ok=True)
        noop = d / "bin" / "xdg-open"        # программа входа не открывает свой браузер: адрес откроем мы
        if not noop.exists():
            noop.write_text("#!/bin/sh\nexit 0\n")
            noop.chmod(0o700)
        self.out = d / (re.sub(r"[^\w.-]+", "_", connwatch.key(c)) + ".out")
        self.out.unlink(missing_ok=True)
        env = {**os.environ, "PATH": f"{d / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}", "BROWSER": "true"}
        self.clock, self.sleep = clock, sleep
        self.p = popen([sys.executable, "-c", HOLD_PY, str(HOLD), str(self.out), *cmd], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, cwd=str(Path.home()),
                       start_new_session=True)
        self.cmd = " ".join(shlex.quote(x) for x in cmd)

    def text(self) -> str:
        try:
            return _ANSI.sub("", self.out.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return ""

    def exit_code(self) -> int | None:
        m = _EXIT.search(self.text())
        return int(m.group(1)) if m else None

    def url(self, timeout: float = URL_WAIT) -> str:
        end = self.clock() + timeout
        while self.clock() < end:
            t = self.text()
            if m := _URL.search(t):
                return m.group(0).rstrip(".,)")
            if self.exit_code() is not None:
                break
            self.sleep(0.5)
        raise Fail(f"{self.cmd}: адреса входа нет" + (f" (код {self.exit_code()})" if self.exit_code() is not None
                                                      else ""))

    def wait(self, timeout: float) -> int | None:
        end = self.clock() + timeout
        while self.clock() < end:
            if (code := self.exit_code()) is not None:
                return code
            self.sleep(1)
        return None


# ---------- главное ----------
def _result(outcome: str, why: str, c: dict, fp: dict | None = None, extra: str = "") -> connwatch.Result:
    hint = (extra + " " if extra else "") + connwatch.hint(c)
    return connwatch.Result(outcome == "clicked", scrub(why)[:300], hint, outcome=outcome, fp=fp)


def run(c: dict, approved: dict | None = None, *, browser=None, start=None, verify=None, vault=None,
        clock=time.monotonic, sleep=time.sleep) -> connwatch.Result:
    """Войти заново. Итог — ``Result.outcome``: clicked (вошёл сам) · needs_owner (вкладка открыта, задача
    «Ждут вас») · failed (техническая причина). ``approved`` — отпечаток, который владелец уже разрешал."""
    if c.get("state") != "needs_auth":
        return _result("needs_owner", "сервер не запускается — это не вход", c)
    if c["harness"] not in LOGIN:
        return _result("needs_owner", f"{c['harness']}: команды входа без сессии нет", c)
    b = browser or Browser()
    if not b.alive():
        return _result("failed", "браузер агента (DevTools) не отвечает", c)
    vault = vault or connwatch.vault_get
    try:
        lg = (start or Login)(c)
        auth = lg.url()
        b.open(auth)
    except (Fail, OSError) as e:
        return _result("failed", str(e), c)
    try:
        return _drive(c, approved, b, lg, auth, verify, vault, clock, sleep)
    except Exception as e:                                        # сбой автовхода не роняет сторожа
        return _result("failed", f"{type(e).__name__}: {e}"[:200], c)
    finally:
        b.detach()


def _drive(c, approved, b, lg, auth, verify, vault, clock, sleep) -> connwatch.Result:
    open_tab = "В Chrome агента («Браузер» на столе) уже открыта страница входа."
    end, filled = clock() + PAGE_WAIT, False
    s, k = {}, "unknown"
    while clock() < end:
        s = b.snap()
        k = kind(s) if s.get("ready") == "complete" else "loading"
        h = host(s.get("url", ""))
        if k in ("callback",):
            break
        if k in ("captcha", "twofa"):
            what = "капча" if k == "captcha" else "двухфакторная проверка"
            return _result("needs_owner", f"{h}: {what} — не обходим", c, extra=open_tab)
        if k == "password":
            if filled:
                sleep(1)
                continue
            if domain_in(h, NEVER_PASSWORD):
                return _result("needs_owner", f"{h}: пароль Google и Telegram не вводим", c, extra=open_tab)
            svc = next((d for d in PASSWORD_SERVICES if domain_in(h, [d])), "")
            if not svc:
                return _result("needs_owner", f"{h}: вход по паролю — сервис не в списке разрешённых", c,
                               extra=open_tab)
            entry = f"{c['harness']}/{c['name']}"
            pw = vault(entry)
            if not pw:
                return _result("needs_owner", f"{h}: в базе паролей нет записи {entry}", c, extra=open_tab)
            user = vault(entry, attr="username") if s.get("user") else None
            if user:
                b.fill(USER_JS, user)
            ok = b.fill(PASS_JS, pw)
            del pw                                                # значение дальше не держим
            if not ok:
                return _result("needs_owner", f"{h}: поле пароля не нашлось", c, extra=open_tab)
            b.enter()
            filled = True
            sleep(2)
            continue
        if k == "consent":
            fp = fingerprint(s.get("url", ""), auth, s.get("perms"))
            btn = allow_buttons(s)
            if not approved:
                return _result("needs_owner", f"{h}: первый вход — «Разрешить» нажимает владелец", c, fp,
                               extra=open_tab)
            if approved.get("fp") != fp["fp"]:
                return _result("needs_owner", f"{h}: права изменились (было {approved.get('scope')}, стало "
                               f"{fp['scope']}) — решает владелец", c, fp, extra=open_tab)
            if len(set(btn)) != 1:
                return _result("needs_owner", f"{h}: кнопок «Разрешить» не одна — решает владелец", c, fp,
                               extra=open_tab)
            if not b.click(btn[0]):
                return _result("failed", f"{h}: кнопка «{btn[0]}» не нажалась", c, fp)
            return _after_click(c, fp, b, lg, verify, clock, sleep)
        sleep(1)                                                  # загрузка или переадресация — подождать
    if k == "callback" or lg.exit_code() == 0:                    # вход прошёл без согласия (уже разрешено)
        return _verify(c, None, lg, verify, "без страницы согласия")
    why = "после ввода пароля снова страница входа" if filled and k == "password" else "страница не распознана"
    return _result("needs_owner", f"{host(s.get('url', '')) or 'страница'}: {why}", c, extra=open_tab)


def _after_click(c, fp, b, lg, verify, clock, sleep) -> connwatch.Result:
    code = lg.wait(AFTER_CLICK)
    if code is None:
        return _result("failed", "нажал «Разрешить», но программа входа не закончила", c, fp)
    return _verify(c, fp, lg, verify, "нажал «Разрешить»", code)


def _verify(c, fp, lg, verify, how: str, code: int | None = None) -> connwatch.Result:
    code = lg.wait(AFTER_CLICK) if code is None else code
    if code not in (0, None):
        return _result("failed", f"{how}, программа входа: код {code}", c, fp)
    items = (verify or connwatch.check)(c["harness"])
    st = next((x["state"] for x in items if x["name"] == c["name"]), "unknown")
    if st != "ok":
        return _result("failed", f"{how}, но коннектор {st}", c, fp)
    return _result("clicked", how, c, fp)
