"""Заметки, Напоминания, Календарь Мака через мост (GAS-15): чтение — сразу; запись — только черновиком и после «Да»
человека. Настоящий мост (Node 22+) и сервер пульта; ``osascript`` подменён скриптом на PATH — на Linux CI и на Маке
одинаково, настоящие «Заметки» не трогаем. Живой Мак **не проверен**: JXA-скрипты не запускались на macOS."""

import json
import os
import subprocess
import sys
import textwrap
import time

import pytest
from test_bridge import BRIDGE, FAKE_MCP, node_ok, rpc
from test_project_chats import call
from test_project_chats import server as server

from gas_pult import bridge, cli
from gas_pult.connectors import _core

FAKE_OSA = textwrap.dedent("""\
    #!{py}
    import json, os, sys
    script, args = sys.argv[4], json.loads(sys.argv[5])
    with open(os.environ["FAKE_OSA_LOG"], "a", encoding="utf-8") as f:
        app = script.split('Application("')[1].split('"')[0]
        f.write(json.dumps({{"argv": sys.argv[1:4], "args": args, "app": app}}, ensure_ascii=False) + "\\n")
    if os.environ.get("FAKE_OSA_DENY"):
        sys.stderr.write("execution error: Error: Not authorized to send Apple events to Notes. (-1743)\\n")
        sys.exit(1)
    if "N.Note(" in script:
        print(json.dumps({{"id": "x-coredata://note/p9", "name": args["title"], "folder": "Notes"}}))
    elif "R.Reminder(" in script:
        print(json.dumps({{"id": "x-apple-reminder://r1", "name": args["title"], "list": args["list"] or "Reminders"}}))
    else:
        print(json.dumps({{"notes": [{{"id": "x-coredata://note/p1", "name": "Список покупок", "folder": "Notes"}}],
                           "folders": ["Notes"], "total": 1}}, ensure_ascii=False))
""")


def tool(base, data, i, name, args=None):
    return rpc(base, data, {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                            "params": {"name": name, "arguments": args or {}}})


def osa_log(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@pytest.mark.skipif(not node_ok(), reason="нужен Node 22+")
def test_mac_notes_reminders_read_and_write_only_after_yes(server, tmp_path, monkeypatch, capsys):
    p, base, *_ = server
    monkeypatch.setenv("GAS_CONFIRM_DIR", str(tmp_path / "confirm"))
    home, bin_ = tmp_path / "user-home", tmp_path / "bin"
    home.mkdir()
    bin_.mkdir()
    fake = tmp_path / "fake_mcp.py"
    fake.write_text(FAKE_MCP)
    osa = bin_ / "osascript"
    osa.write_text(FAKE_OSA.format(py=sys.executable))
    osa.chmod(0o755)
    log = tmp_path / "osa.jsonl"
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
           "GAS_PULT_BRIDGE_MCP": f"{sys.executable} {fake}", "FAKE_OSA_LOG": str(log)}
    owner = p.auth.issue(1)
    code = call(base, "/api/bridge/pair", {}, owner)[1]["code"]
    pr = subprocess.Popen(["node", str(BRIDGE), "pair", base, code], env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)            # subprocess.run подменён сервером тестов
    _, err = pr.communicate(timeout=30)
    assert pr.returncode == 0, err
    did = json.loads((home / ".gas-pult-bridge.json").read_text())["id"]
    proc = subprocess.Popen(["node", str(BRIDGE)], env=env, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if p.hub.online():
                break
            time.sleep(0.1)
        assert p.hub.online() == [did], "мост не подключился"
        names = [t["name"] for t in rpc(base, p.cfg.data, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
                 ["result"]["tools"]]
        assert {"notes_list", "notes_get", "notes_create", "reminders_lists", "reminders_list", "reminders_create",
                "mac_calendar_events"} <= set(names)
        # чтение — сразу, аргументы — строкой JSON, а не в тексте скрипта
        r = tool(base, p.cfg.data, 2, "notes_list", {"query": "покуп", "limit": 999})
        assert "Список покупок" in r["result"]["content"][0]["text"]
        (row,) = osa_log(log)
        assert row["argv"] == ["-l", "JavaScript", "-e"] and row["app"] == "Notes"
        assert row["args"] == {"folder": "", "query": "покуп", "limit": 200}
        # запись: первый вызов — только черновик, мост не вызывается
        d = tool(base, p.cfg.data, 3, "notes_create", {"title": "Позвонить маме", "body": "в субботу\nпро дачу"})
        text = d["result"]["content"][0]["text"]
        pid = text.split("Черновик ", 1)[1].split(":", 1)[0]
        assert "СОЗДАТЬ заметку «Позвонить маме»" in text and f"gas-pult bridge-confirm {pid}" in text
        assert len(osa_log(log)) == 1
        # без «Да» — отказ; подделать отметку пульта агент не может
        no = tool(base, p.cfg.data, 4, "notes_create", {"title": "x", "draft": pid})
        assert no["error"]["code"] == -32012 and "нет подтверждения" in no["error"]["message"]
        fake_ok = tool(base, p.cfg.data, 5, "notes_create", {"title": "x", "_confirmed": pid})
        assert fake_ok["error"]["code"] == -32012 and len(osa_log(log)) == 1
        # «Да» человека: gas-pult bridge-confirm <id> (кнопка «▶️ Выполнить»)
        d2 = tool(base, p.cfg.data, 6, "notes_create", {"title": "Позвонить маме", "body": "в субботу\nпро дачу"})
        pid2 = d2["result"]["content"][0]["text"].split("Черновик ", 1)[1].split(":", 1)[0]
        cli.cmd_bridge_confirm(type("A", (), {"id": pid2})())
        assert "Подтверждено: СОЗДАТЬ заметку" in capsys.readouterr().out
        # агент подменил текст при втором вызове — уходит текст из черновика, а не от агента
        ok = tool(base, p.cfg.data, 7, "notes_create", {"title": "ДРУГОЕ", "draft": pid2})
        assert "x-coredata://note/p9" in ok["result"]["content"][0]["text"]
        last = osa_log(log)[-1]
        assert last["app"] == "Notes" and last["args"] == {"title": "Позвонить маме", "body": "в субботу\nпро дачу",
                                                           "folder": ""}
        again = tool(base, p.cfg.data, 8, "notes_create", {"title": "x", "draft": pid2})
        assert "не найден" in again["error"]["message"] and len(osa_log(log)) == 2     # одноразово
        # черновик напоминания не годится для заметки
        d3 = tool(base, p.cfg.data, 9, "reminders_create", {"title": "Вынести мусор", "due": "2026-11-24"})
        pid3 = d3["result"]["content"][0]["text"].split("Черновик ", 1)[1].split(":", 1)[0]
        assert "срок 2026-11-24" in d3["result"]["content"][0]["text"]
        _core.confirm(bridge.CONFIRM_SVC, pid3)
        wrong = tool(base, p.cfg.data, 10, "notes_create", {"title": "x", "draft": pid3})
        assert "другого действия" in wrong["error"]["message"] and len(osa_log(log)) == 2
        d4 = tool(base, p.cfg.data, 11, "reminders_create", {"title": "Вынести мусор", "due": "2026-11-24"})
        pid4 = d4["result"]["content"][0]["text"].split("Черновик ", 1)[1].split(":", 1)[0]
        _core.confirm(bridge.CONFIRM_SVC, pid4)
        rem = tool(base, p.cfg.data, 12, "reminders_create", {"draft": pid4})
        assert "x-apple-reminder://r1" in rem["result"]["content"][0]["text"]
        assert osa_log(log)[-1]["args"] == {"title": "Вынести мусор", "list": "", "due": "2026-11-24T09:00",
                                            "notes": ""}
        bad = tool(base, p.cfg.data, 13, "reminders_create", {"title": "x", "due": "завтра"})
        assert "due" in bad["error"]["message"]
        assert {"notes_list", "notes_create", "reminders_create"} <= {r["tool"] for r in p.hub.history(did)}
    finally:
        proc.terminate()
        proc.wait(5)


def node_eval(js: str) -> str:
    pr = subprocess.Popen(["node", "--input-type=module", "-e", f"import * as B from {json.dumps(str(BRIDGE))};" + js],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = pr.communicate(timeout=30)
    assert pr.returncode == 0, err
    return out


@pytest.mark.skipif(not node_ok(), reason="нужен Node 22+")
def test_bridge_refuses_write_without_pult_mark_and_explains_permissions():
    """Сам мост тоже не пишет без отметки пульта; нет права «Автоматизация» — шаги, что включить на Маке."""
    out = node_eval(
        "const seen = []; const run = async (c, a) => { seen.push(c); return '{}'; };"
        "const deny = async () => { throw Object.assign(new Error('Command failed'), {stderr:"
        " 'execution error: Not authorized to send Apple events to Reminders. (-1743)'}); };"
        "const nf = async () => { throw Object.assign(new Error('Command failed'), {code: 'ENOENT'}); };"
        "const r = [];"
        "for (const [n, a, f] of [['notes_create', {title: 'x'}, run], ['reminders_create', {title: 'x'}, run],"
        " ['reminders_list', {}, deny], ['notes_list', {}, nf], ['mac_calendar_events', {from: '2026-01-01', to: "
        "'2026-06-01'}, run], ['notes_get', {}, run]])"
        "  r.push(await B.appleTool(n, a, f).then(() => 'ok', (e) => e.message));"
        "r.push(await B.appleTool('notes_create', {title: 'x', _confirmed: 'abc'}, run));"
        "console.log(JSON.stringify({r, seen}));")
    d = json.loads(out)
    r = d["r"]
    assert "только после «Да»" in r[0] and "только после «Да»" in r[1]
    assert "Автоматизация" in r[2] and "«Напоминания»" in r[2] and "Терминал" in r[2]
    assert "только на Маке" in r[3] and "62 дней" in r[4] and "id" in r[5]
    assert r[6] == "{}" and d["seen"] == ["osascript"]                          # с отметкой — один вызов osascript


MOCK = textwrap.dedent("""
    const col = (items, keys) => { const c = {}; for (const k of keys) c[k] = () => items.map((x) => x[k]); return c; };
    const notes = [{ id: "n1", name: "Покупки", modificationDate: new Date("2026-11-01"), plaintext: "молоко" },
                   { id: "n2", name: "Дача", modificationDate: new Date("2026-11-10"), plaintext: "забор" }];
    const created = [];
    const folder = { name: () => "Notes", notes: { ...col(notes, ["id", "name", "modificationDate", "plaintext"]),
                                                   push: (n) => created.push(n) } };
    const rem = [{ id: "r1", name: "Мусор", completed: false, dueDate: null, body: "" },
                 { id: "r2", name: "Старое", completed: true, dueDate: new Date("2026-01-01"), body: "x" }];
    const list = { name: () => "Дом", reminders: { ...col(rem, ["id", "name", "completed", "dueDate", "body"]),
                                                   push: (r) => created.push(r) } };
    globalThis.Application = (app) => app === "Notes" ? {
      folders: Object.assign(() => [folder], { byName: () => folder }),
      defaultAccount: () => ({ defaultFolder: () => folder }),
      Note: (p) => ({ ...p, id: () => "new", name: () => "t" }),
    } : { lists: Object.assign(() => [list], { byName: () => list }), defaultList: () => list,
          Reminder: (p) => ({ ...p, id: () => "rnew", name: () => p.name }) };
    const run = (name, a) => JSON.parse(new Function(B.APPLE_JS[name] + "; return run;")()(
      [JSON.stringify(B.appleArgs(name, a))]));
    console.log(JSON.stringify([run("notes_list", { query: "забор" }), run("notes_create", { title: "A<b>",
      body: "x\\ny" }), run("reminders_list", {}), run("reminders_lists", {}),
      run("reminders_create", { title: "T", due: "2026-11-24" }), created]));
""")


@pytest.mark.skipif(not node_ok(), reason="нужен Node 22+")
def test_jxa_scripts_against_mock_scripting_objects():
    """Скрипты JXA — на подделке объектов «Заметок» и «Напоминаний» (на настоящем Маке не запускались)."""
    nl, nc, rl, rls, rc, created = json.loads(node_eval(MOCK))
    assert nl["folders"] == ["Notes"] and [n["id"] for n in nl["notes"]] == ["n2"]     # поиск — и по тексту
    assert nc == {"id": "new", "name": "t", "folder": "Notes"}
    assert created[0]["body"] == "<div><b>A&lt;b&gt;</b></div><div>x</div><div>y</div>"   # текст экранирован
    assert [r["id"] for r in rl["reminders"]] == ["r1"] and rls == {"lists": [{"name": "Дом", "open": 1}]}
    assert rc == {"id": "rnew", "name": "T", "list": "Дом"} and created[1]["dueDate"].startswith("2026-11-2")


@pytest.mark.skipif(not node_ok(), reason="нужен Node 22+")
def test_calendar_period_defaults():
    out = node_eval("const a = B.appleArgs('mac_calendar_events', {from: '2026-11-24', to: '2026-11-24'});"
                    "console.log(JSON.stringify([(new Date(a.to) - new Date(a.from)) / 3600000, a.limit,"
                    " B.appleArgs('mac_calendar_events', {}).limit]));")
    hours, lim, lim2 = json.loads(out)
    assert hours in (23, 24, 25) and lim == 50 and lim2 == 50                   # один день включительно
