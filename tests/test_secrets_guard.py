"""Скрытие секретов от модели (secrets_guard.py, задача 44): распознаватели, хук, установка, панель.

Образцы — заведомо поддельные и собраны склейкой строк, чтобы их не принял за настоящие сканер секретов GitHub.
Настоящий claude не запускается: хук проверяется подпроцессом с JSON на стандартном вводе, как его зовёт Claude Code.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from websrc import web_source

from gas_pult import secrets_guard as g
from gas_pult import tenant_admin, transcripts

SRC = Path(g.__file__)
HTML = SRC.parent / "web" / "index.html"


def j(*parts):
    return "".join(parts)


A40 = "Ab3" * 14
# (текст, тип, значение — его не должно остаться)
SAMPLES = [
    (j("ключ ", "sk-", "ant-api03-", A40), "ключ Anthropic", j("sk-", "ant-api03-", A40)),
    (j("OPENROUTER=", "sk-", "or-v1-", "0f" * 32), "ключ OpenRouter", j("sk-", "or-v1-", "0f" * 32)),
    (j("вот ", "sk-", "proj-", A40), "ключ OpenAI", j("sk-", "proj-", A40)),
    (j("token ", "gh", "p_", "x" * 36), "токен GitHub", j("gh", "p_", "x" * 36)),
    (j("github", "_pat_", "11AB" * 15), "токен GitHub", j("github", "_pat_", "11AB" * 15)),
    (j("gl", "pat-", "Zx9" * 8), "токен GitLab", j("gl", "pat-", "Zx9" * 8)),
    (j("бот ", "123456789", ":AA", "Fq9" * 11), "токен Telegram-бота", j("123456789", ":AA", "Fq9" * 11)),
    (j("AKIA", "Z" * 12, "7Q2X"), "ключ AWS", j("AKIA", "Z" * 12, "7Q2X")),
    (j("key=", "AIza", "Sy", "D" * 33), "ключ Google", j("AIza", "Sy", "D" * 33)),
    (j("xox", "b-", "1234567890", "-abcdefghij"), "токен Slack", j("xox", "b-", "1234567890", "-abcdefghij")),
    (j("ey", "JhbGciOiJIUzI1NiJ9", ".", "ey", "JzdWIiOiIxMjM0NTY3ODkwIn0", ".", "SflKxwRJSMeKKF2QT4fw"), "токен JWT",
     "SflKxwRJSMeKKF2QT4fw"),
    (j("-----BEGIN ", "OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAA\n-----END ", "OPENSSH PRIVATE KEY-----"),
     "приватный ключ", "b3BlbnNzaC1rZXktdjEAAAA"),
    (j("-----BEGIN ", "RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA"), "приватный ключ", "MIIEpAIBAAKCAQEA"),
    ("DATABASE_URL=postgres://app:" + j("Hu", "nter2", "x9") + "@db:5432/x", "пароль в адресе", j("Hu", "nter2", "x9")),
    ("Authorization: Bearer " + j("abcDEF", "123456", "7890xyz"), "токен в заголовке",
     j("abcDEF", "123456", "7890xyz")),
    (j("DB_PASS", "WORD=", "adm", "in12"), "значение секретной переменной", j("adm", "in12")),
    (j("export MY_API_", "KEY=", "q1w2e3r4t5"), "значение секретной переменной", "q1w2e3r4t5"),
    (j('{"client_', 'secret": "', "s3cr3t", 'Value"}'), "значение секретной переменной", j("s3cr3t", "Value")),
    (j("password: ", "hun", "ter22"), "значение секретной переменной", j("hun", "ter22")),
]
FALSE = [
    "commit 3f2a9c1e5b7d8a0c4e6f1a2b3c4d5e6f7a8b9c0d в main",
    "id 123e4567-e89b-12d3-a456-426614174000",
    "Обычный текст: ключ к успеху — регулярность, пароль от Wi-Fi спросите у администратора.",
    "api_key: Optional[str] = None",
    'API_KEY = os.environ["OPENAI_API_KEY"]',
    "token = get_token(user)",
    "DB_PASSWORD=${DB_PASSWORD}",
    "OPENAI_API_KEY=your-key-here",
    "SECRET_KEY=<вставьте>",
    "max_tokens=4096",
    "password: production",
    "monkey=banana12345",
    "http://localhost:8080/path",
    "git@github.com:user/repo.git",
    "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "[скрыт: ключ OpenAI]",
]


@pytest.mark.parametrize("text,label,value", SAMPLES)
def test_samples_found_and_hidden(text, label, value):
    out, found = g.redact(text)
    assert label in found
    assert value not in out
    assert "[скрыт: " in out


@pytest.mark.parametrize("text", FALSE)
def test_no_false_positives(text):
    assert g.redact(text) == (text, [])


def test_assignment_keeps_name_and_quotes():
    out, _ = g.redact(j('SECRET_KEY = "', "dj4ngo-", 'insecure-zz99"'))
    assert out == 'SECRET_KEY = "[скрыт: значение секретной переменной]"'
    assert g.redact(j("postgres://u:", "p4ss", "w0rd@h/db"))[0] == "postgres://u:[скрыт: пароль в адресе]@h/db"


def test_env_values(tmp_path):
    (tmp_path / ".env").write_text(j("DB_PASSWORD=", "Zz9plain", "\nAPP_ENV=production\nSESSION=", "a1B2" * 5,
                                     "\nDEBUG=true\nX_TOKEN='", "quoted", "Val1'\n"))
    (tmp_path / ".env.example").write_text("DB_PASSWORD=changeme\nX_TOKEN=quotedVal1\n")
    vals = g.env_values(tmp_path)
    assert j("Zz9plain") in vals and "a1B2" * 5 in vals
    assert "production" not in vals and "true" not in vals
    assert "quotedVal1" not in vals                     # заглушка из .env.example — не секрет
    out, found = g.redact(j("pw ", "Zz9plain", " and Zz9plainX"), vals)
    assert out == "pw [скрыт: значение из .env] and Zz9plainX" and found == ["значение из .env"]


@pytest.mark.parametrize("tool,inp,blocked", [
    ("Read", {"file_path": "/w/.env"}, True),
    ("Read", {"file_path": "/w/.env.local"}, True),
    ("Read", {"file_path": "/w/.ENV.production"}, True),
    ("Read", {"file_path": "/w/.envrc"}, True),
    ("Read", {"file_path": "/w/.env.example"}, False),
    ("Read", {"file_path": "/w/.env/lib/site.py"}, False),
    ("Read", {"file_path": "/w/app.py"}, False),
    ("Grep", {"pattern": "KEY", "path": ".env"}, True),
    ("Grep", {"pattern": "KEY", "glob": ".env*"}, True),
    ("Grep", {"pattern": "KEY", "path": "src"}, False),
    ("Bash", {"command": "cat .env"}, True),
    ("Bash", {"command": "grep KEY ./.env.local | head"}, True),
    ("Bash", {"command": "source .env && env"}, True),
    ("Bash", {"command": "cat .env.example"}, False),
    ("Bash", {"command": "ls -a"}, False),
    ("Bash", {"command": "ls -la .env"}, False),
    ("Bash", {"command": ".env/bin/python -V"}, False),
    ("Bash", {"command": "pytest -q"}, False),
])
def test_env_blocking(tool, inp, blocked):
    assert bool(g.env_target(tool, inp)) is blocked


def run_hook(data, script=SRC):
    r = subprocess.run([sys.executable, str(script), "hook"], input=json.dumps(data), capture_output=True, text=True,
                       timeout=20)
    assert r.returncode == 0
    return (json.loads(r.stdout) if r.stdout.strip() else None), r


def test_hook_prompt_blocked_without_value(tmp_path):
    key = j("sk-", "ant-api03-", A40)
    out, r = run_hook({"hook_event_name": "UserPromptSubmit", "cwd": str(tmp_path), "prompt": "вот " + key})
    assert out["decision"] == "block" and out["hookSpecificOutput"]["suppressOriginalPrompt"] is True
    assert "Убрал ключ" in out["reason"] and "ключ Anthropic" in out["reason"] and "«Интеграции»" in out["reason"]
    assert key not in r.stdout + r.stderr
    assert run_hook({"hook_event_name": "UserPromptSubmit", "cwd": str(tmp_path), "prompt": "привет"})[0] is None


def test_hook_post_tool_rewrites_same_shape(tmp_path):
    key = j("gh", "p_", "y" * 36)
    (tmp_path / ".env").write_text(j("DB_PASSWORD=", "Qq7local", "\n"))
    resp = {"stdout": f"token {key}\nconn Qq7local ok", "stderr": "", "interrupted": False, "isImage": False}
    out, r = run_hook({"hook_event_name": "PostToolUse", "cwd": str(tmp_path), "tool_name": "Bash",
                       "tool_input": {"command": "x"}, "tool_response": resp})
    new = out["hookSpecificOutput"]["updatedToolOutput"]
    assert set(new) == set(resp) and new["interrupted"] is False and new["isImage"] is False
    assert new["stdout"] == "token [скрыт: токен GitHub]\nconn [скрыт: значение из .env] ok"
    assert key not in r.stdout + r.stderr and "Qq7local" not in r.stdout + r.stderr
    # Read: вложенная форма {type, file: {content}}; без секретов — хук молчит
    read = {"type": "text", "file": {"filePath": "/w/a.py", "content": "print(1)", "numLines": 1}}
    assert run_hook({"hook_event_name": "PostToolUse", "cwd": str(tmp_path), "tool_name": "Read",
                     "tool_response": read})[0] is None


def test_hook_pre_tool_denies_env(tmp_path):
    out, _ = run_hook({"hook_event_name": "PreToolUse", "cwd": str(tmp_path), "tool_name": "Read",
                       "tool_input": {"file_path": str(tmp_path / ".env")}})
    h = out["hookSpecificOutput"]
    assert h["permissionDecision"] == "deny" and ".env.example" in h["permissionDecisionReason"]
    assert run_hook({"hook_event_name": "PreToolUse", "cwd": str(tmp_path), "tool_name": "Read",
                     "tool_input": {"file_path": str(tmp_path / ".env.example")}})[0] is None


def test_hook_bad_input_is_harmless():
    r = subprocess.run([sys.executable, str(SRC), "hook"], input="не json", capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == ""


def test_script_is_self_contained(tmp_path):
    """Копия хука работает без пакета gas_pult: пространство не видит код пульта в домашней папке владельца."""
    assert not re.search(r"^\s*(from|import) gas_pult", SRC.read_text(), re.M)
    copy = tmp_path / "hooks" / g.SCRIPT
    copy.parent.mkdir()
    shutil.copy(SRC, copy)
    r = subprocess.run([sys.executable, "-I", str(copy), "hook"], cwd=tmp_path, capture_output=True, text=True,
                       input=json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": str(tmp_path),
                                         "prompt": j("AKIA", "Q" * 16)}))
    assert json.loads(r.stdout)["decision"] == "block"


def test_install_idempotent_backup_keeps_foreign(tmp_path):
    d = tmp_path / "claude"
    d.mkdir()
    foreign = {"model": "opus", "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [
        {"type": "command", "command": "lint.sh"}]}], "Stop": [{"hooks": [{"type": "command", "command": "bye"}]}]}}
    (d / "settings.json").write_text(json.dumps(foreign))
    r1 = g.install(d, python="/usr/bin/python3", out=None)
    assert r1["changed"] and r1["backup"] and json.loads(Path(r1["backup"]).read_text()) == foreign
    s = json.loads((d / "settings.json").read_text())
    assert s["model"] == "opus" and s["hooks"]["Stop"] == foreign["hooks"]["Stop"]
    assert s["hooks"]["PostToolUse"][0] == foreign["hooks"]["PostToolUse"][0] and len(s["hooks"]["PostToolUse"]) == 2
    assert all(any(g.TAG in h["command"] for grp in s["hooks"][ev] for h in grp["hooks"]) for ev in g.EVENTS)
    assert (d / "hooks" / g.SCRIPT).read_text() == SRC.read_text() and g.installed(d)
    before = (d / "settings.json").read_text()
    r2 = g.install(d, python="/usr/bin/python3", out=None)
    assert not r2["changed"] and not r2["backup"] and (d / "settings.json").read_text() == before
    assert len(list(d.glob("settings.json.bak-*"))) == 1
    g.install(d, remove=True, out=None)
    assert json.loads((d / "settings.json").read_text()) == foreign and not g.installed(d)


def test_install_fresh_dir_and_bad_json(tmp_path):
    d = tmp_path / "new"
    r = g.install(d, python="python3", out=None)
    assert r["changed"] and r["backup"] is None and g.installed(d)
    assert (d / "settings.json").stat().st_mode & 0o777 == 0o600
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "settings.json").write_text("[1]")
    with pytest.raises(ValueError):
        g.install(bad, out=None)
    assert (bad / "settings.json").read_text() == "[1]"


def test_person_dir_gets_guard(tmp_path):
    from gas_pult import people

    d = people.claude_dir(tmp_path, 2002, [1001])
    assert g.installed(d)


def test_tenant_create_writes_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(tenant_admin.shutil, "chown", lambda *a, **k: None)   # root в тесте нет: владельца не меняем
    lay = tenant_admin.Layout(tmp_path / "srv", tmp_path / "etc")
    claude = tmp_path / "t" / "config" / "claude"
    claude.mkdir(parents=True)
    (claude / "settings.json").write_text(json.dumps({"theme": "dark"}))
    out = []
    s = tenant_admin.Sys(dry=False, out=out.append)
    u = __import__("getpass").getuser()
    tenant_admin.guard(s, claude, u, lay, python="/usr/bin/python3")
    st = json.loads((claude / "settings.json").read_text())
    assert st["theme"] == "dark" and g.TAG in json.dumps(st["hooks"]) and "/usr/bin/python3" in json.dumps(st)
    assert (claude / "hooks" / g.SCRIPT).is_file() and list((lay.etc_backup).glob("settings.json.*"))
    out.clear()
    tenant_admin.guard(s, claude, u, lay, python="/usr/bin/python3")
    assert not any(x.startswith("запись") for x in out)        # повторно — без изменений


def test_tenant_create_dry_run_mentions_guard(tmp_path):
    out = []
    s = tenant_admin.Sys(dry=True, out=out.append)
    tenant_admin.guard(s, tmp_path / "c", "nobody", None)
    assert any(g.SCRIPT in x for x in out) and any("settings.json" in x for x in out)
    assert not (tmp_path / "c").exists()


def test_transcript_shows_block_note_not_key(tmp_path):
    key = j("sk-", "ant-api03-", A40)
    proj = tmp_path / "projects" / "-w"
    proj.mkdir(parents=True)
    lines = [{"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-11-07T10:00:00Z",
              "content": "вот " + key},
             {"type": "queue-operation", "operation": "dequeue", "timestamp": "2026-11-07T10:00:00Z"},
             {"type": "system", "subtype": "informational", "timestamp": "2026-11-07T10:00:01Z",
              "content": "UserPromptSubmit operation blocked by hook:\n" + g.prompt_reason(["ключ Anthropic"])}]
    (proj / "s.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")
    items, _ = transcripts.history("/w", home=tmp_path)
    assert key not in json.dumps(items, ensure_ascii=False)
    assert [x["role"] for x in items] == ["assistant"] and items[0]["text"].startswith("Убрал ключ")
    assert items[0]["note"] == "blocked"


# ---------- панель: те же правила и то же поведение ----------
def html_rules():
    m = re.search(r'<script type="application/json" id="secretRules">\n(.*?)\n</script>', web_source(), re.S)
    return json.loads(m.group(1))


def test_panel_rules_are_copy_of_python():
    assert html_rules() == [{k: r[k] for k in ("id", "label", "re", "flags", "g")} for r in g.RULES]


def test_panel_checks_before_send():
    h = web_source()
    body = h[h.index("async function sendText()"):h.index("const msgId")]
    assert body.index("redactSecrets(typed)") < body.index("pending.push")
    assert 'helpSheet("sheet.secret")' in h and "Убрать и отправить" in h and "Отправить как есть" in h


def test_panel_js_matches_python():
    node = shutil.which("node") or os.environ.get("NODE")
    if not node:
        pytest.skip("нет node — поведение JS проверяет CI (ubuntu, node есть)")
    h = web_source()
    code = h[h.index("// secrets:begin"):h.index("// secrets:end")]
    texts = [t for t, _, _ in SAMPLES] + FALSE
    prog = ("const document = { getElementById: () => ({ textContent: process.argv[1] }) };\n" + code
            + "\nconst texts = JSON.parse(process.argv[2]);\n"
              "process.stdout.write(JSON.stringify(texts.map((t) => { const r = redactSecrets(t); "
              "return [r.text, r.found]; })));")
    r = subprocess.run([node, "-e", prog, json.dumps(html_rules()), json.dumps(texts)], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [list(g.redact(t)) for t in texts]
