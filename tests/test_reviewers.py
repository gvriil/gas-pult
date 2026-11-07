"""Слепые проверяющие (задача 45): файлы агентов, сторож и раскладка в пространства модулей и демо-пространства."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from gas_pult import modules, reviewers, tenant_admin, tenants

SRC = reviewers.source_dir()
GUARD = SRC / reviewers.GUARD


def front(text: str) -> tuple[dict, str]:
    """Простой разбор frontmatter: ключи верхнего уровня (строки «ключ: значение») и тело."""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert m, "нет frontmatter между ---"
    keys = {}
    for line in m.group(1).splitlines():
        if (k := re.match(r"^([A-Za-z]+):\s*(.*)$", line)):
            keys[k.group(1)] = k.group(2).strip()
    return keys, m.group(2)


@pytest.fixture(autouse=True)
def own_config(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))


# --- файлы агентов ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", list(reviewers.AGENTS))
def test_agent_file_valid(name):
    text = (SRC / f"{name}.md").read_text(encoding="utf-8")
    keys, body = front(text)
    assert keys["name"] == name and re.fullmatch(r"[a-z][a-z-]+", name)
    assert re.search(r"[а-яё]{4}", keys["description"]) and len(keys["description"]) > 60
    assert {t.strip() for t in keys["tools"].split(",")} == {"Read", "Grep", "Glob"}     # только чтение
    assert keys["omitClaudeMd"] == "true"                    # без CLAUDE.md пользователя, проекта и локального
    assert "memory" not in keys                              # своей памяти агента нет
    assert "PreToolUse" in text and reviewers.GUARD in text and 'matcher: "*"' in text
    for status in ("«принято»", "«принято с замечаниями»", "«не принято»", "«не проверял"):
        assert status in body, status
    assert "Первая строка" in body
    # публичный репозиторий: ни секретов, ни личных путей, ни длинных номеров, ни латинских имён людей
    assert not re.search(r"/home/|/Users/|sk-[A-Za-z0-9]|ghp_|\d{8,}", text)
    latin = set(re.findall(r"\b[A-Za-z][A-Za-z]+\b", body)) - {"PDF"}
    assert not latin, latin
    assert not re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", text)          # «Имя Фамилия» латиницей


def test_names_agree():
    src = GUARD.read_text(encoding="utf-8")
    names = set(re.search(r"NAMES = \{(.*?)\}", src).group(1).replace('"', "").replace(" ", "").split(","))
    assert names == set(reviewers.AGENTS)
    assert not re.search(r"/home/|\d{8,}", src)


def test_documents_agent_modes():
    body = front((SRC / "slepaya-proverka-dokumentov.md").read_text(encoding="utf-8"))[1]
    for want in ("Как налоговая", "Как банк", "115-ФЗ", "камеральн", "ст. 9", "ст. 169", "ст. 54.1", "ячейка"):
        assert want in body, want


# --- сторож ---------------------------------------------------------------------------------------------------------

def run_guard(event: dict, cwd: Path) -> dict | None:
    r = subprocess.run([sys.executable, "-I", str(GUARD)], input=json.dumps(event), capture_output=True, text=True,
                       cwd=cwd, timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None


@pytest.fixture
def scene(tmp_path):
    """Сессия с журналом агента: задание называет папку результата и файл с пробелом в имени."""
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "CLAUDE.md").write_text("правила автора\n")
    (proj / "src" / "a.py").write_text("x = 1\n")
    (proj / "secret.txt").write_text("не для проверяющего\n")
    res = tmp_path / "result"
    (res / "sub").mkdir(parents=True)
    (res / "отчёт.md").write_text("итог\n")
    (res / "sub" / "CLAUDE.md").write_text("правила подпапки\n")
    (res / "sub" / "b.md").write_text("b\n")
    docs = tmp_path / "Документы клиента"
    docs.mkdir()
    (docs / "акт 1.pdf").write_text("pdf")
    sessions = tmp_path / "cfg" / "projects" / "p"
    (sessions / "s1" / "subagents").mkdir(parents=True)
    task = (f"Зачем: проверить результат.\nТребование: отчёт по пунктам.\nГде смотреть: {res}/ и «{docs}/акт 1.pdf», "
            "а также src/a.py.\nОтвет: статус первой строкой.")
    (sessions / "s1" / "subagents" / "agent-a1.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": task}}, ensure_ascii=False) + "\n"
        + json.dumps({"type": "user", "message": {"role": "user", "content": f"и ещё {proj}/secret.txt"}}) + "\n")
    base = {"hook_event_name": "PreToolUse", "transcript_path": str(sessions / "s1.jsonl"), "agent_id": "a1",
            "agent_type": "slepaya-proverka", "cwd": str(proj)}
    return {"proj": proj, "res": res, "docs": docs, "base": base, "tmp": tmp_path}


def ev(sc, tool, **inp):
    return {**sc["base"], "tool_name": tool, "tool_input": inp}


def test_guard_allows_only_passed_paths(scene):
    sc, cwd = scene, scene["proj"]
    assert run_guard(ev(sc, "Read", file_path=str(sc["res"] / "отчёт.md")), cwd) is None
    assert run_guard(ev(sc, "Read", file_path=str(sc["docs"] / "акт 1.pdf")), cwd) is None      # путь с пробелом
    assert run_guard(ev(sc, "Read", file_path=str(cwd / "src" / "a.py")), cwd) is None           # относительный
    assert run_guard(ev(sc, "Grep", pattern="итог", path=str(sc["res"])), cwd) is None
    assert run_guard(ev(sc, "Glob", pattern="**/*.md", path=str(sc["res"])), cwd) is None
    # вне задания — отказ: файл проекта, второе сообщение (не задание), поиск по рабочей папке, выход через «..»
    for e in (ev(sc, "Read", file_path=str(cwd / "secret.txt")),
              ev(sc, "Read", file_path=str(sc["res"] / ".." / "proj" / "secret.txt")),
              ev(sc, "Grep", pattern="x"),
              ev(sc, "Glob", pattern="/etc/*"),
              ev(sc, "Glob", pattern="../proj/*", path=str(sc["res"]))):
        out = run_guard(e, cwd)
        assert out and out["permissionDecision"] == "deny", e


def test_guard_symlink_out_of_scope(scene):
    link = scene["res"] / "ссылка.txt"
    link.symlink_to(scene["proj"] / "secret.txt")
    out = run_guard(ev(scene, "Read", file_path=str(link)), scene["proj"])
    assert out and out["permissionDecision"] == "deny"


def test_guard_closes_rules_memory_and_tools(scene):
    sc, cwd = scene, scene["proj"]
    for e in (ev(sc, "Read", file_path=str(cwd / "CLAUDE.md")),
              ev(sc, "Read", file_path=str(sc["res"] / "MEMORY.md")),
              ev(sc, "Read", file_path=str(sc["tmp"] / "cfg" / "projects" / "p" / "s1.jsonl")),
              ev(sc, "Grep", pattern="x", path=str(sc["res"]), glob="CLAUDE.md"),
              ev(sc, "Bash", command=f"cat {sc['res']}/отчёт.md"),
              ev(sc, "Write", file_path=str(sc["res"] / "x.md"), content="x")):
        out = run_guard(e, cwd)
        assert out and out["permissionDecision"] == "deny", e
    # файл в папке со своим CLAUDE.md — отказ с объяснением (Read подложил бы правила папки)
    out = run_guard(ev(sc, "Read", file_path=str(sc["res"] / "sub" / "b.md")), cwd)
    assert out and "своими правилами" in out["permissionDecisionReason"]


def test_guard_fail_closed_and_scope(scene, tmp_path):
    sc, cwd = scene, scene["proj"]
    # нет журнала агента — задания не видно — закрыто
    out = run_guard({**ev(sc, "Read", file_path=str(sc["res"] / "отчёт.md")), "agent_id": "нет"}, cwd)
    assert out and out["permissionDecision"] == "deny"
    # агент документов — тот же сторож; другие агенты и главная сессия — сторож их не трогает
    assert run_guard({**ev(sc, "Read", file_path=str(sc["res"] / "отчёт.md")),
                      "agent_type": "slepaya-proverka-dokumentov"}, cwd) is None
    assert run_guard({**ev(sc, "Bash", command="ls"), "agent_type": "general-purpose"}, cwd) is None
    assert run_guard({k: v for k, v in ev(sc, "Bash", command="ls").items() if k != "agent_type"}, cwd) is None
    # мусор на входе — отказ, не пропуск
    r = subprocess.run([sys.executable, "-I", str(GUARD)], input="{не json", capture_output=True, text=True, cwd=cwd)
    assert r.returncode == 0 and json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_guard_ignores_too_wide_roots(scene, monkeypatch):
    sys.path.insert(0, str(SRC))
    try:
        import slepaya_proverka_storozh as g
    finally:
        sys.path.remove(str(SRC))
    monkeypatch.setenv("HOME", str(scene["tmp"]))
    roots = g.allowed_roots("смотри / и ~ и ~/ и /tmp, а ещё и/или", str(scene["proj"]))
    assert str(Path("/").resolve()) not in roots and str(scene["tmp"]) not in roots


def test_hook_command_from_frontmatter(scene, tmp_path):
    """Команда хука из определения: сторож из .claude проекта, иначе — из папки Claude Code; нет — стоп (код 2)."""
    text = (SRC / "slepaya-proverka.md").read_text(encoding="utf-8")
    cmd = re.search(r"command: '(.*)'", text).group(1)
    e = json.dumps(ev(scene, "Bash", command="ls"))
    proj, conf = tmp_path / "p2", tmp_path / "c2"
    proj.mkdir()
    env = {"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_CONFIG_DIR": str(conf),
           "HOME": str(tmp_path)}
    r = subprocess.run(["sh", "-c", cmd], input=e, capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "не установлен" in r.stderr
    reviewers.install(conf)
    r = subprocess.run(["sh", "-c", cmd], input=e, capture_output=True, text=True, env=env)
    assert r.returncode == 0 and json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- раскладка ------------------------------------------------------------------------------------------------------

def test_install_idempotent(tmp_path):
    d = tmp_path / ".claude"
    first = reviewers.install(d)
    assert sorted(first) == sorted(reviewers.files())
    assert reviewers.install(d) == []
    (d / "agents" / "slepaya-proverka.md").write_text("испорчено")
    (d / "agents" / "моё.md").write_text("свой агент")
    assert reviewers.install(d) == ["agents/slepaya-proverka.md"]
    assert (d / "agents" / "моё.md").read_text() == "свой агент"
    assert (d / "hooks" / reviewers.GUARD).stat().st_mode & 0o777 == 0o755


def test_module_workspace_gets_reviewers(tmp_path, monkeypatch):
    monkeypatch.setattr(modules.subprocess, "run", lambda *a, **k: None)
    dst = modules.create("acc-primary", tmp_path / "projects", "buh")
    for rel in reviewers.files():
        assert (dst / ".claude" / rel).is_file(), rel
    assert modules.get("acc-primary")["agents"] == reviewers.public()


def lay_of(tmp_path):
    lay = tenant_admin.Layout(tmp_path / "srv", tmp_path / "etc")
    (tmp_path / "etc").mkdir()
    lay.fstab.write_text("UUID=1 / ext4 defaults 0 1\n")
    lay.tenants.mkdir(parents=True)
    (lay.tenants / ".enabled").write_text(json.dumps({"owner": "someone", "tmux": "/usr/bin/tmux"}))
    return lay


def fake_sys(monkeypatch, out):
    monkeypatch.setattr(tenant_admin, "user_exists", lambda u: True)
    monkeypatch.setattr(tenant_admin, "mounted", lambda p, *a: True)
    monkeypatch.setattr(tenant_admin, "_uid", lambda u: None)
    monkeypatch.setattr(tenant_admin, "_gid", lambda g: None)
    monkeypatch.setattr(tenant_admin.shutil, "chown", lambda *a, **k: None)
    return tenant_admin.Sys(out=out.append, runner=lambda argv, **k: subprocess.CompletedProcess(argv, 0, "", ""))


def test_tenant_space_gets_reviewers(tmp_path, monkeypatch):
    lay, said = lay_of(tmp_path), []
    s = fake_sys(monkeypatch, said)
    (lay.tenants / "buh-demo").mkdir()
    tenant_admin.create(lay, s, "buh-demo", jurisdiction="RU")
    claude = tenants.paths("buh-demo", lay.tenants)["claude"]
    for rel, text in reviewers.files().items():
        assert (claude / rel).read_text(encoding="utf-8") == text
    assert (claude / "hooks").stat().st_mode & 0o777 == 0o755
    assert (claude / "agents").stat().st_mode & 0o777 == 0o700
    assert (claude / "hooks" / reviewers.GUARD).stat().st_mode & 0o777 == 0o755
    # повторно — ни одной записи; испорченный файл — восстановлен командой agents (без имени — во все пространства)
    said.clear()
    tenant_admin.agents(lay, s, [])
    assert not any(x.startswith("запись") for x in said) and any("buh-demo" in x for x in said)
    (claude / "agents" / "slepaya-proverka.md").write_text("испорчено")
    said.clear()
    assert tenant_admin.parser().parse_args(["agents", "buh-demo"]).slugs == ["buh-demo"]
    tenant_admin.agents(lay, s, ["buh-demo"])
    assert [x for x in said if x.startswith("запись")] and (claude / "agents" / "slepaya-proverka.md").read_text() \
        == reviewers.files()["agents/slepaya-proverka.md"]
    with pytest.raises(ValueError, match="нет пространства"):
        tenant_admin.agents(lay, s, ["nope"])


def test_tenant_dry_run_writes_nothing(tmp_path):
    lay, out = lay_of(tmp_path), []
    tenant_admin.create(lay, tenant_admin.Sys(dry=True, out=out.append), "buh-demo", jurisdiction="RU")
    text = "\n".join(out)
    assert "config/claude/agents/slepaya-proverka.md" in text and f"config/claude/hooks/{reviewers.GUARD}" in text
    assert not (lay.tenants / "buh-demo").exists()
