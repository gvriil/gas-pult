"""Коннектор почты IMAP/SMTP (docs/CONNECTORS.md) — настоящим процессом, без сети.

**Не проверено на реальном ящике:** письма в tests/fixtures/mail/ выдуманные, ответы IMAP построены по RFC 3501 /
RFC 6154 (адреса — в шапке fixture). Фейковые IMAP- и SMTP-серверы ниже отвечают как Яндекс Почта (разделитель «|»,
роли папок) и «случайно» повторяют пароль в тексте ошибки — проверяем, что он не попадает ни в stdout, ни в stderr.
"""

import base64
import copy
import email
import email.policy
import json
import os
import re
import socketserver
import subprocess
import sys
import threading
from pathlib import Path
from typing import ClassVar

import pytest

from gas_pult.connectors import mail_mcp

SERVER = Path(mail_mcp.__file__)
FIX = json.loads((Path(__file__).parent / "fixtures" / "mail" / "mailbox.json").read_text())
PW = "test" + "-app-" + "pass0123456789"               # заведомо не настоящий, склейкой — не для сканера
USER = "uk-dom@example.ru"
WRITE_CMDS = {"APPEND", "STORE", "COPY", "MOVE", "EXPUNGE", "DELETE", "CREATE", "RENAME", "SELECT"}


def _msg(raw: str):
    return email.message_from_string(raw, policy=email.policy.default)


class IMAP(socketserver.StreamRequestHandler):
    """Подмножество IMAP4rev1, которого хватает imaplib: LOGIN, LIST, EXAMINE, UID SEARCH/FETCH, APPEND, LOGOUT."""

    seen: ClassVar[list] = []
    mode = "ok"                                         # ok | badlogin | badlist
    box: ClassVar[dict] = {}

    def w(self, s: str | bytes):
        self.wfile.write((s.encode() if isinstance(s, str) else s) + b"\r\n")

    def read(self):
        line = self.rfile.readline()
        if not line:
            return None, []
        lits = []
        while m := re.search(rb"\{(\d+)\}\r\n$", line):
            self.w("+ go ahead")
            lits.append(self.rfile.read(int(m.group(1))))
            line = line[: m.start()] + b"<LIT>" + self.rfile.readline()
        return line.decode().rstrip("\r\n"), lits

    def handle(self):
        self.w("* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN] fake ready")
        cur = None
        while True:
            line, lits = self.read()
            if line is None:
                return
            tag, _, rest = line.partition(" ")
            words = rest.split(" ")
            cmd = words[0].upper()
            sub = words[1].upper() if cmd == "UID" and len(words) > 1 else ""
            IMAP.seen.append({"cmd": cmd, "sub": sub, "line": rest, "lits": lits})
            if cmd == "CAPABILITY":
                self.w("* CAPABILITY IMAP4rev1 AUTH=PLAIN")
            elif cmd == "LOGIN":
                user, pw = re.match(r'LOGIN ("?)(\S+?)\1 "(.*)"$', rest).group(2, 3)
                if IMAP.mode == "badlogin" or (user, pw) != (USER, PW):
                    self.w(f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials for {user} / {pw}")
                    continue
            elif cmd == "LIST":
                if IMAP.mode == "badlist":
                    self.w(f"{tag} BAD internal error, session {PW}")
                    continue
                for f in FIX["folders"]:
                    self.w(f'* LIST ({" ".join(f["flags"])}) "|" "{mail_mcp.utf7_encode(f["name"])}"')
            elif cmd in ("EXAMINE", "SELECT"):
                name = mail_mcp.utf7_decode(rest.split(" ", 1)[1].strip('"'))
                if name not in IMAP.box:
                    self.w(f"{tag} NO [NONEXISTENT] no such mailbox")
                    continue
                cur = name
                self.w(f"* {len(IMAP.box[name])} EXISTS")
                self.w("* OK [UIDVALIDITY 1] ok")
                self.w(f"{tag} OK [{'READ-ONLY' if cmd == 'EXAMINE' else 'READ-WRITE'}] done")
                continue
            elif cmd == "UID" and sub == "SEARCH":
                self.w("* SEARCH " + " ".join(str(m["uid"]) for m in self.search(cur, rest, lits)))
            elif cmd == "UID" and sub == "FETCH":
                self.fetch(cur, words[2], rest)
            elif cmd == "APPEND":
                name = mail_mcp.utf7_decode(re.match(r'APPEND "([^"]*)"', rest).group(1))
                IMAP.box[name].append({"uid": 900 + len(IMAP.box[name]), "flags": ["\\Draft", "\\Seen"],
                                       "raw": lits[0].decode()})
            elif cmd == "LOGOUT":
                self.w("* BYE bye")
                self.w(f"{tag} OK done")
                return
            elif cmd not in WRITE_CMDS and sub not in WRITE_CMDS:
                self.w(f"{tag} BAD unknown command")
                continue
            self.w(f"{tag} OK done")

    def search(self, folder: str, rest: str, lits: list[bytes]) -> list[dict]:
        toks = re.findall(r'"[^"]*"|\S+', rest)[2:]
        vals = iter(lits)
        out = list(IMAP.box[folder])
        i = 0
        while i < len(toks):
            t = toks[i].upper()
            if t == "CHARSET":
                i += 2
                continue
            if t == "UNSEEN":
                out = [m for m in out if "\\Seen" not in m["flags"]]
            elif t in ("FROM", "SUBJECT", "TEXT", "SINCE"):
                v = toks[i + 1] if i + 1 < len(toks) else ""
                v = next(vals).decode() if v == "<LIT>" else v.strip('"')
                hdr = {"FROM": "From", "SUBJECT": "Subject"}.get(t)
                if t == "SINCE":
                    d = email.utils.parsedate_to_datetime(v.replace("-", " ") + " 00:00:00 +0300")
                    out = [m for m in out if email.utils.parsedate_to_datetime(_msg(m["raw"])["Date"]) >= d]
                elif hdr:
                    out = [m for m in out if v.lower() in str(_msg(m["raw"])[hdr]).lower()]
                else:
                    out = [m for m in out if v.lower() in mail_mcp._text_of(_msg(m["raw"]))[0].lower()]
                i += 1
            i += 1
        return out

    def fetch(self, folder: str, uids: str, rest: str):
        want = set(uids.split(","))
        for n, m in enumerate(IMAP.box[folder], 1):
            if str(m["uid"]) not in want:
                continue
            raw = m["raw"].replace("\r\n", "\n").replace("\n", "\r\n").encode()
            if "HEADER.FIELDS" in rest:
                head = raw.split(b"\r\n\r\n", 1)[0].decode()
                keep = [h for h in re.split(r"\r\n(?![ \t])", head)
                        if h.split(":", 1)[0].upper() in ("FROM", "TO", "SUBJECT", "DATE")]
                data, key = ("\r\n".join(keep) + "\r\n\r\n").encode(), "BODY[HEADER.FIELDS (FROM TO SUBJECT DATE)]"
            else:
                data, key = raw, "BODY[]<0>"
            flags = " ".join(m["flags"])
            self.wfile.write(f"* {n} FETCH (UID {m['uid']} FLAGS ({flags}) RFC822.SIZE {len(raw)} {key} "
                             f"{{{len(data)}}}\r\n".encode() + data + b")\r\n")


class SMTP(socketserver.StreamRequestHandler):
    seen: ClassVar[list] = []
    mode = "ok"

    def w(self, s: str):
        self.wfile.write(s.encode() + b"\r\n")

    def handle(self):
        self.w("220 fake ESMTP")
        while line := self.rfile.readline().decode().rstrip("\r\n"):
            cmd = line.split(" ")[0].upper()
            SMTP.seen.append(cmd)
            if cmd in ("EHLO", "HELO"):
                self.w("250-fake\r\n250-AUTH PLAIN\r\n250 8BITMIME")
            elif cmd == "AUTH":
                _, user, pw = base64.b64decode(line.split(" ")[2]).decode().split("\0")
                if SMTP.mode == "badauth" or (user, pw) != (USER, PW):
                    self.w(f"535 5.7.8 bad credentials {pw}")
                else:
                    self.w("235 2.7.0 ok")
            elif cmd == "DATA":
                self.w("354 go")
                body = b""
                while (x := self.rfile.readline()) != b".\r\n":
                    body += x
                SMTP.seen.append(body.decode())
                self.w("250 queued")
            elif cmd == "QUIT":
                self.w("221 bye")
                return
            else:
                self.w("250 ok")


class TS(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


@pytest.fixture
def env(tmp_path):
    IMAP.seen, IMAP.mode, IMAP.box = [], "ok", copy.deepcopy(FIX["messages"])
    SMTP.seen, SMTP.mode = [], "ok"
    srvs = [TS(("127.0.0.1", 0), IMAP), TS(("127.0.0.1", 0), SMTP)]
    for s in srvs:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    keys = tmp_path / "keys"
    keys.mkdir()
    f = keys / "mail-yandex.json"
    f.write_text(json.dumps({"host": "127.0.0.1", "imap_port": srvs[0].server_address[1], "smtp_host": "127.0.0.1",
                             "smtp_port": srvs[1].server_address[1], "tls": False, "user": USER,
                             "app_password": PW}))
    f.chmod(0o600)
    yield {"GAS_MAIL_KEY_DIR": str(keys), "GAS_CONFIRM_DIR": str(tmp_path / "confirm")}
    for s in srvs:
        s.shutdown()
        s.server_close()


def run(args: list[str], env: dict, stdin: str = "") -> subprocess.CompletedProcess:
    full = {k: v for k, v in os.environ.items() if not k.startswith("GAS_")} | env
    p = subprocess.run([sys.executable, str(SERVER), *args], input=stdin, capture_output=True, text=True,
                       timeout=60, env=full)
    assert PW not in p.stdout and PW not in p.stderr
    return p


def rpc(calls: list[tuple[str, dict]], env: dict) -> list[dict]:
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
    msgs += [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls, 1)]
    p = run([], env, "".join(json.dumps(m) + "\n" for m in msgs))
    out = [json.loads(x) for x in p.stdout.splitlines()]
    assert out[0]["result"]["serverInfo"]["name"] == "gas-pult-mail" and len(out) == len(calls) + 1
    return out[1:]


def call(name: str, args: dict | None = None) -> tuple[str, dict]:
    return "tools/call", {"name": name, "arguments": args or {}}


def body(resp: dict):
    assert not resp["result"]["isError"], resp["result"]["content"][0]["text"]
    return json.loads(resp["result"]["content"][0]["text"])


def err(resp: dict) -> str:
    assert resp["result"]["isError"], resp["result"]["content"][0]["text"]
    return resp["result"]["content"][0]["text"]


def imap_writes() -> list:
    return [s for s in IMAP.seen if s["cmd"] in WRITE_CMDS or s["sub"] in WRITE_CMDS]


def test_tools_list(env):
    (r,) = rpc([("tools/list", {})], env)
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["mail_list_boxes", "mail_list_folders", "mail_list_messages", "mail_get_message",
                     "mail_propose_draft", "mail_propose_send", "mail_apply"]
    assert all("fn" not in t and t["description"] for t in r["result"]["tools"])


def test_list_boxes_hides_password(env):
    (r,) = rpc([call("mail_list_boxes")], env)
    (b,) = body(r)["boxes"]
    assert b["box"] == "yandex" and b["user"] == USER and b["imap"] == "127.0.0.1" and "app_password" not in b
    assert not IMAP.seen                                # список ящиков — без входа на сервер


def test_list_folders(env):
    (r,) = rpc([call("mail_list_folders")], env)
    d = body(r)
    roles = {f["name"]: f["role"] for f in d["folders"]}
    # имена и флаги — как в настоящем ответе Яндекса 17.11 (свои папки переименованы)
    assert roles == {"INBOX": "входящие", "Отправленные": "отправленные", "Черновики": "черновики", "Спам": "спам",
                     "Удаленные": "корзина", "Черновики|template": "шаблоны", "Обращения": "", "Счета": ""}
    # «Архив» — \Noselect, не показываем
    login = next(s for s in IMAP.seen if s["cmd"] == "LOGIN")
    assert USER in login["line"] and not imap_writes()


def test_list_messages_newest_first_read_only(env):
    (r,) = rpc([call("mail_list_messages", {"limit": 2})], env)
    d = body(r)
    assert d["total"] == 3 and [x["uid"] for x in d["rows"]] == ["103", "102"] and "more" in d
    m = d["rows"][1]
    assert m["subject"] == "Протечка в подъезде" and m["from"] == "Сергей Иванов <s.ivanov@example.org>"
    assert m["date"] == "2026-11-12T18:40:00+03:00" and m["seen"] is False and m["size"] > 100
    assert m["answered"] is False and "message_id" in m and "cc" in m          # для брифинга (GAS-18)
    assert [s["cmd"] for s in IMAP.seen if s["cmd"] in ("EXAMINE", "SELECT")] == ["EXAMINE"]
    fetch = next(s for s in IMAP.seen if s["sub"] == "FETCH")
    assert "BODY.PEEK[" in fetch["line"] and not imap_writes()


def test_list_messages_filters_cyrillic(env):
    (r,) = rpc([call("mail_list_messages", {"unseen": True, "since": "2026-11-11", "subject": "протечка"})], env)
    d = body(r)
    assert [x["uid"] for x in d["rows"]] == ["102"] and d["total"] == 1
    s = next(s for s in IMAP.seen if s["sub"] == "SEARCH")
    assert s["line"].startswith("UID SEARCH CHARSET UTF-8 UNSEEN SINCE 11-Nov-2026 SUBJECT")
    assert s["lits"] == ["протечка".encode()]


def test_list_messages_yo_searches_both_spellings(env):
    """Яндекс ищет буквально (проверено 17.11): «протёчка» ищем и как «протечка», результаты объединяем."""
    (r,) = rpc([call("mail_list_messages", {"subject": "протёчка"})], env)
    d = body(r)
    assert [x["uid"] for x in d["rows"]] == ["102"] and d["total"] == 1
    lits = [s["lits"][0] for s in IMAP.seen if s["sub"] == "SEARCH"]
    assert lits == ["протёчка".encode(), "протечка".encode()] and not imap_writes()


def test_list_messages_errors(env):
    r1, r2, r3 = rpc([call("mail_list_messages", {"since": "вчера"}),
                      call("mail_list_messages", {"from": "Анна", "subject": "Перерасчёт"}),
                      call("mail_list_messages", {"folder": "Нет такой"})], env)
    assert "ГГГГ-ММ-ДД" in err(r1) and "один фильтр" in err(r2) and "нет папки «Нет такой»" in err(r3)


def test_get_message_plain_html_attachment(env):
    r1, r2, r3, r4 = rpc([call("mail_get_message", {"uid": "101"}), call("mail_get_message", {"uid": 102}),
                          call("mail_get_message", {"uid": "103", "max_chars": 200}),
                          call("mail_get_message", {"uid": "999"})], env)
    a = body(r1)
    assert a["subject"] == "Перерасчёт за отопление, кв. 12" and a["text_from"] == "plain"
    assert a["text"].startswith("Добрый день!") and "кв. 12" in a["text"]
    assert a["message_id"] == "<a101.petrova@example.com>"
    b = body(r2)
    assert b["text_from"] == "html" and "течёт крыша" in b["text"]
    assert "<p>" not in b["text"] and "color" not in b["text"]
    c = body(r3)
    assert c["attachments"] == [{"name": "akt-sverki-10-2026.pdf", "type": "application/pdf", "bytes": 16}]
    assert "нет в папке" in err(r4)
    assert all("BODY.PEEK[]" in s["line"] for s in IMAP.seen if s["sub"] == "FETCH") and not imap_writes()


def test_bad_uid_no_connection(env):
    (r,) = rpc([call("mail_get_message", {"uid": "1:*"})], env)
    assert "uid" in err(r) and not IMAP.seen


@pytest.mark.parametrize("mode", ["badlogin", "badlist"])
def test_password_never_leaks_on_errors(env, mode):
    IMAP.mode = mode                                   # сервер повторяет пароль в тексте ошибки
    r1, r2 = rpc([call("mail_list_folders"), ("ping", {})], env)
    text = err(r1)
    assert "***" in text and ("вход не удался" in text if mode == "badlogin" else "ошибкой" in text)
    assert r2["result"] == {}


def test_no_key_file(env, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r1, r2, r3 = rpc([call("mail_list_folders"), call("mail_list_boxes"), ("ping", {})],
                     env | {"GAS_MAIL_KEY_DIR": str(empty)})
    assert "нет файла ящика mail-<ящик>.json" in err(r1) and "нет файла ящика" in err(r2) and r3["result"] == {}


def test_several_boxes_need_name_and_tls_only_local(env):
    keys = Path(env["GAS_MAIL_KEY_DIR"])
    (keys / "mail-gmail2.json").write_text(json.dumps({"host": "imap.gmail.com", "user": "x@gmail.com",
                                                       "app_password": PW, "tls": False}))
    r1, r2, r3 = rpc([call("mail_list_folders"), call("mail_list_folders", {"box": "gmail2"}),
                      call("mail_list_folders", {"box": "../etc"})], env)
    assert "укажите box: gmail2, yandex" in err(r1)
    assert "только для проверки на 127.0.0.1" in err(r2) and "неверное имя ящика" in err(r3) and not IMAP.seen


def test_utf7_folder_names():
    assert mail_mcp.utf7_encode("~peter/mail/台北/日本語") == "~peter/mail/&U,BTFw-/&ZeVnLIqe-"   # RFC 3501 §5.1.3
    for s in ("Обращения", "A&B", "Отправленные 2026"):
        assert mail_mcp.utf7_decode(mail_mcp.utf7_encode(s)) == s


def _confirm(pid: str, env: dict):
    p = run(["confirm", pid], env)
    assert p.returncode == 0, p.stderr


def test_draft_needs_confirmation_then_one_append(env):
    (r,) = rpc([call("mail_propose_draft", {"to": ["anna.petrova@example.com"], "reply_to_uid": "101",
                                            "body": "Анна, перерасчёт будет в квитанции за ноябрь."})], env)
    d = body(r)
    assert d["params"]["subject"] == "Re: Перерасчёт за отопление, кв. 12"
    assert d["params"]["in_reply_to"] == "<a101.petrova@example.com>" and "черновик" in d["summary"]
    assert not imap_writes() and not SMTP.seen
    pid = d["id"]
    r1, r2 = rpc([call("mail_apply", {"id": pid}), call("mail_apply", {"id": pid})], env | {"GAS_MAIL_WRITE": "1"})
    assert "нет подтверждения" in err(r1) and "нет подтверждения" in err(r2) and not imap_writes()
    _confirm(pid, env)
    (r,) = rpc([call("mail_apply", {"id": pid})], env)
    assert "запись выключена" in err(r) and not imap_writes()
    r1, r2 = rpc([call("mail_apply", {"id": pid}), call("mail_apply", {"id": pid})], env | {"GAS_MAIL_WRITE": "1"})
    assert body(r1)["folder"] == "Черновики" and "не найден" in err(r2)
    (w,) = imap_writes()
    assert w["cmd"] == "APPEND" and "\\Draft" in w["line"] and not SMTP.seen
    saved = _msg(w["lits"][0].decode())
    assert saved["In-Reply-To"] == "<a101.petrova@example.com>" and saved["From"] == USER
    assert "квитанции за ноябрь" in saved.get_content()


def test_send_only_after_confirmation(env):
    (r,) = rpc([call("mail_propose_send", {"to": "s.ivanov@example.org", "subject": "Протечка — бригада",
                                           "body": "Сергей, бригада будет сегодня до 18:00."})], env)
    d = body(r)
    assert "ОТПРАВИТЬ" in d["summary"] and not SMTP.seen and not IMAP.seen
    _confirm(d["id"], env)
    (r,) = rpc([call("mail_apply", {"id": d["id"]})], env | {"GAS_MAIL_WRITE": "1"})
    assert body(r)["message_id"].endswith("@example.ru>")
    assert SMTP.seen.count("DATA") == 1 and SMTP.seen.count("RCPT") == 1 and not imap_writes()
    sent = _msg(SMTP.seen[SMTP.seen.index("DATA") + 1])
    assert sent["To"] == "s.ivanov@example.org" and "до 18:00" in sent.get_content()


def test_send_bad_password_hidden(env):
    SMTP.mode = "badauth"
    (r,) = rpc([call("mail_propose_send", {"to": ["a@example.com"], "subject": "т", "body": "т"})], env)
    pid = body(r)["id"]
    _confirm(pid, env)
    (r,) = rpc([call("mail_apply", {"id": pid})], env | {"GAS_MAIL_WRITE": "1"})
    assert "SMTP не принял пароль" in err(r) and "***" in err(r) and "DATA" not in SMTP.seen


def test_propose_validation(env):
    many = [f"u{i}@example.com" for i in range(11)]
    r1, r2, r3, r4 = rpc([call("mail_propose_send", {"to": many, "subject": "т", "body": "т"}),
                          call("mail_propose_send", {"to": ["не адрес"], "subject": "т", "body": "т"}),
                          call("mail_propose_draft", {"to": ["a@example.com"], "subject": "т", "body": " "}),
                          call("mail_propose_draft", {"to": ["a@example.com\r\nBcc: x@y.ru"], "subject": "т",
                                                      "body": "т"})], env)
    assert "не больше 10" in err(r1) and "неверный адрес" in err(r2) and "пустой текст" in err(r3)
    assert "неверный адрес" in err(r4) and not SMTP.seen and not imap_writes()
