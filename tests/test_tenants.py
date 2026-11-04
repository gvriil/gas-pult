"""Демо-пространства (задача 25, часть A): API пульта (tenants.py) и скрипты владельца (tenant_admin.py,
bin/pult-tenant-setup). Ничего системного: sudo, useradd, mount, systemctl — моком или сухим прогоном."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gas_pult import models, tenant_admin, tenants, tmux

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def clean_cache():
    tenants._ready.clear()
    yield
    tenants._ready.clear()


def no_subprocess(monkeypatch):
    """Любой вызов subprocess — провал теста: функция выключена, sudo трогать нельзя."""
    def boom(*a, **kw):
        raise AssertionError(f"неожиданный вызов: {a}")
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(tmux.subprocess, "run", boom)


def make_tenant(root: Path, slug="demo", jurisdiction="", profile="openrouter", budget=3.0, **extra):
    base = root / slug
    base.mkdir(parents=True)
    (base / "tenant.json").write_text(json.dumps({"title": "Демо", "jurisdiction": jurisdiction, "persona":
                                                  "business_owner", "profile": profile, **extra}))
    (base / "budget.json").write_text(json.dumps({"daily_usd": budget}))
    return base


def enable(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / ".enabled").write_text(json.dumps({"owner": "someone", "tmux": "/usr/bin/tmux"}))


# --- выключено — пульт как раньше --------------------------------------------------------------------------------

def test_disabled_without_setup_no_sudo(tmp_path, monkeypatch):
    no_subprocess(monkeypatch)
    root = tmp_path / "tenants"
    make_tenant(root)                                     # папки есть, а настройки (отметки) нет
    assert not tenants.enabled(root)
    assert tenants.status(root, check=True) == {"enabled": False, "tenants": []}
    assert not tenants.ready("demo", root)
    with pytest.raises(RuntimeError, match="выключены"):
        tenants.new_window("demo", "w", base_root=root)


def test_default_root_absent_is_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_TENANTS_ROOT", str(tmp_path / "nope"))
    assert not tenants.enabled() and tenants.status() == {"enabled": False, "tenants": []}


def test_tmux_without_user_unchanged():
    t = tmux.Tmux("main", socket="/x/s")
    assert t.tmux == ["tmux", "-S", "/x/s"] and t.user == "" and t.shell() == os.environ.get("SHELL", "/bin/bash")
    assert tmux.Tmux("main").tmux[:1] == ["tmux"]


# --- окна пространства: sudo -u … tmux -S … -----------------------------------------------------------------------

def test_tmux_for_tenant_uses_sudo_prefix(monkeypatch):
    runs = []
    monkeypatch.setattr(tmux.subprocess, "run", lambda args, **kw: runs.append(args) or
                        subprocess.CompletedProcess(args, 0 if "has-session" not in args else 1, "@7\n", ""))
    t = tmux.Tmux("main", socket="/srv/t/demo/run/tmux/default", user="pult_t_demo", home="/srv/t/demo/home",
                  tmux="/usr/bin/tmux")
    assert t.new_window("w", "/srv/t/demo/home", "claude") == "@7"
    pre = ["sudo", "-n", "-u", "pult_t_demo", "/usr/bin/tmux", "-S", "/srv/t/demo/run/tmux/default"]
    assert all(r[:7] == pre for r in runs)
    new_session = next(r for r in runs if "new-session" in r)
    assert new_session[new_session.index("-c") + 1] == "/srv/t/demo/home"     # не домашняя папка пульта
    assert not any("systemd-run" in r for r in runs)
    nw = next(r for r in runs if "new-window" in r)
    assert nw[-1] == "claude; exec /bin/bash"           # у пользователя пространства входа нет — оболочка явно
    with pytest.raises(ValueError):
        tmux.Tmux("main", user="pult_t_demo")           # без своего сокета — нельзя


def test_tmux_of_and_new_window(tmp_path, monkeypatch):
    root = tmp_path / "tenants"
    enable(root)
    make_tenant(root, "demo-1")
    runs = []

    def fake(args, **kw):
        runs.append(args)
        return subprocess.CompletedProcess(args, 0, "@3\n", "")
    monkeypatch.setattr(tenants.subprocess, "run", fake)
    monkeypatch.setattr(tmux.subprocess, "run", fake)
    assert tenants.new_window("demo-1", "w", base_root=root) == "@3"
    assert runs[0][:4] == ["sudo", "-n", "-u", "pult_t_demo_1"] and runs[0][-1] == "-V"    # проверка sudo
    nw = next(r for r in runs if "new-window" in r)
    cmd = nw[-1]
    assert f"CLAUDE_CONFIG_DIR={root}/demo-1/config/claude" in cmd
    assert f"--settings {root}/demo-1/config/profiles/openrouter.json" in cmd
    assert ".claude " not in cmd and str(Path.home()) not in cmd
    assert models.profile_of(cmd.split("; ")[1].split()[1:]) == "openrouter"   # после export PATH


def test_ready_cached_and_safe(tmp_path):
    root = tmp_path / "tenants"
    enable(root)
    calls = []

    def runner(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 1, "", "sudo: a password is required")
    clock = iter([0, 1, 100, 101]).__next__
    assert not tenants.ready("demo", root, runner, clock)
    assert not tenants.ready("demo", root, runner, clock)
    assert len(calls) == 1                               # кэш
    assert calls[0][1]["timeout"] == tenants.SUDO_TIMEOUT and "-n" in calls[0][0]
    assert tenants.ready("demo", root, lambda c, **k: subprocess.CompletedProcess(c, 0), clock)  # кэш истёк

    def timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 5)
    tenants._ready.clear()
    assert not tenants.ready("demo", root, timeout)


def test_status_lists_public_fields(tmp_path):
    root = tmp_path / "tenants"
    enable(root)
    make_tenant(root, "demo", jurisdiction="NL", budget=5)
    make_tenant(root, "ru-shop", jurisdiction="RU", profile="gigachat", claude_login=False)
    (root / "Bad_Name").mkdir()
    st = tenants.status(root, check=True, runner=lambda c, **k: subprocess.CompletedProcess(c, 0))
    assert st["enabled"] and [t["slug"] for t in st["tenants"]] == ["demo", "ru-shop"]
    t = st["tenants"][0]
    assert t == {"slug": "demo", "title": "Демо", "jurisdiction": "NL", "persona": "business_owner",
                 "profile": "openrouter", "budget_usd": 5.0, "user": "pult_t_demo", "claude_login": False,
                 "ready": True}
    assert "secret" not in json.dumps(st)


# --- имена, профили, юрисдикция ----------------------------------------------------------------------------------

@pytest.mark.parametrize("slug", ["ab", "demo", "demo-1", "a" * 24, "shop-2026"])
def test_slug_ok(slug):
    assert tenants.check_slug(slug) == slug and len(tenants.user_of(slug)) <= 31


@pytest.mark.parametrize("slug", ["", "a", "1demo", "Demo", "de_mo", "demo-", "-demo", "de--mo", "a" * 25, "../x",
                                  "demo x", "дем"])
def test_slug_bad(slug):
    with pytest.raises(ValueError):
        tenants.check_slug(slug)


def test_user_and_units_names():
    assert tenants.user_of("demo-1") == "pult_t_demo_1"       # дефис в юните systemd — вложенность slice
    un = tenant_admin.Layout().units("demo-1")
    assert un["slice"].name == "pult_t_demo_1.slice" and un["service"].name == "pult_t_demo_1.service"


def test_profiles_by_jurisdiction():
    assert tenants.api_profiles("RU") == ["gigachat", "yandexgpt"]        # только российские — как models.allowed
    assert all(models.allowed(p, "RU") for p in tenants.api_profiles("RU"))
    assert tenants.default_profile("RU") == "gigachat"
    assert tenants.default_profile("NL") == "openrouter" and tenants.default_profile("") == "openrouter"
    assert "claude" not in tenants.api_profiles("NL")                     # по умолчанию — не подписка
    for bad in ("openrouter", "zai", "deepseek", "claude"):
        with pytest.raises(ValueError):
            tenants.check_profile(bad, "RU", login=True)
    with pytest.raises(ValueError, match="только для ваших тестов"):
        tenants.check_profile("claude", "NL")
    assert tenants.check_profile("claude", "NL", login=True) == "claude"
    with pytest.raises(ValueError):
        tenants.check_jurisdiction("Russia")


def test_command_claude_only_after_login(tmp_path):
    t = {"slug": "demo", "jurisdiction": "NL", "profile": "claude"}
    with pytest.raises(ValueError):
        tenants.command(t, base_root=tmp_path)
    cmd = tenants.command(t | {"claude_login": True}, base_root=tmp_path)
    assert cmd == (f"export PATH={tmp_path}/demo/home/.local/bin:/usr/local/bin:/usr/bin:/bin; "
                   f"CLAUDE_CONFIG_DIR={tmp_path}/demo/config/claude claude")
    assert "warning" in tenants.public(t | {"claude_login": True})


@pytest.mark.parametrize("profile", ["claude", "openrouter"])
def test_command_finds_claude_in_space_home_without_its_path(tmp_path, profile):
    """Окно пространства получает окружение клиента tmux — sudo с secure_path без home/.local/bin пространства.
    Команда сама ставит PATH: claude находится, тот же PATH — у его программ и у оболочки после выхода (buh-demo)."""
    home = tmp_path / "demo/home"
    fake = home / ".local/bin/claude"
    fake.parent.mkdir(parents=True)
    fake.write_text('#!/bin/sh\necho "claude $* | $CLAUDE_CONFIG_DIR | $PATH"\n')
    fake.chmod(0o755)
    t = {"slug": "demo", "jurisdiction": "NL", "profile": profile, "claude_login": True}
    cmd = tenants.command(t, base_root=tmp_path)
    secure = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin"     # как sudo secure_path
    r = subprocess.run(["sh", "-c", f'{cmd} --continue; echo "after | $PATH"'], capture_output=True, text=True,
                       env={"PATH": secure}, cwd=tmp_path)
    assert r.returncode == 0 and "command not found" not in r.stderr, r.stderr
    first, after = r.stdout.splitlines()
    want = f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin"
    assert first.startswith("claude ") and first.endswith(f" | {tmp_path}/demo/config/claude | {want}")
    assert "--continue" in first and ("--settings" in first) == (profile != "claude")
    assert after == f"after | {want}"
    assert tenants.path_env("demo", tmp_path) == want


# --- скрипт владельца: сухой прогон и мок ------------------------------------------------------------------------

def lay_of(tmp_path) -> tenant_admin.Layout:
    lay = tenant_admin.Layout(tmp_path / "srv", tmp_path / "etc")
    (tmp_path / "etc").mkdir()
    lay.fstab.write_text("UUID=1 / ext4 defaults 0 1\n")
    return lay


def test_create_dry_run_changes_nothing(tmp_path):
    lay = lay_of(tmp_path)
    out = []
    meta = tenant_admin.create(lay, tenant_admin.Sys(dry=True, out=out.append), "demo", jurisdiction="RU")
    text = "\n".join(out)
    assert meta["profile"] == "gigachat" and meta["persona"] == "business_owner"
    assert "--shell /usr/sbin/nologin" in text and "useradd --system" in text
    assert "fallocate -l 2G" in text and "mkfs.ext4" in text
    assert "loop,nodev,nosuid,nofail" in text and "systemctl enable --now pult_t_demo.service" in text
    assert not (tmp_path / "srv").exists()                                  # ничего не создано
    assert lay.fstab.read_text() == "UUID=1 / ext4 defaults 0 1\n"
    assert ".claude/" not in text.replace("config/claude/", "") and "credentials" not in text


def test_units_limits_and_sandbox():
    lay = tenant_admin.Layout()
    sl = tenant_admin.slice_unit("demo")
    assert "MemoryMax=1G" in sl and "CPUQuota=80%" in sl and "TasksMax=128" in sl
    sv = tenant_admin.service_unit(lay, "demo", "/usr/bin/tmux")
    for want in ("User=pult_t_demo", "Slice=pult_t_demo.slice", "ProtectHome=yes", "ProtectProc=invisible",
                 "ProtectSystem=strict", "ReadWritePaths=/srv/pult/tenants/demo", "NoNewPrivileges=yes",
                 "ExecStart=/usr/bin/tmux -D -f /dev/null -S /srv/pult/tenants/demo/run/tmux/default",
                 "Environment=CLAUDE_CONFIG_DIR=/srv/pult/tenants/demo/config/claude"):
        assert want in sv
    # RestrictSUIDSGID запрещает openat2 (ENOSYS): tar не распаковывает вложенные папки — его нет; suid и так без силы
    assert "RestrictSUIDSGID" not in sv and "NoNewPrivileges=yes" in sv
    share, timer = tenant_admin.share_units(lay, "demo")
    assert "User=pult_t_demo" in share and "chmod g+r" in share and "OnUnitActiveSec=30s" in timer


class FakeSystem:
    """Мок системы для настоящего (не сухого) прогона: команды записываются, chown — ничего, пользователь и
    монтирование — как скажет тест."""

    def __init__(self, monkeypatch):
        self.cmds, self.users, self.mounts = [], set(), set()
        monkeypatch.setattr(tenant_admin, "user_exists", lambda u: u in self.users)
        monkeypatch.setattr(tenant_admin, "mounted", lambda p, *a: str(p) in self.mounts)
        monkeypatch.setattr(tenant_admin, "_uid", lambda u: None)
        monkeypatch.setattr(tenant_admin, "_gid", lambda g: None)
        monkeypatch.setattr(tenant_admin.shutil, "chown", lambda *a, **k: None)

    def runner(self, argv, **kw):
        self.cmds.append(argv)
        if argv[0] == "useradd":
            self.users.add(argv[-1])
        if argv[0] == "mount":
            self.mounts.add(argv[1])
        if argv[0] == "umount":                       # содержимое жило на образе — точка монтирования пуста
            self.mounts.discard(argv[1])
            os.replace(argv[1], argv[1] + ".on-image")
            os.mkdir(argv[1])
        if argv[0] == "fallocate":
            Path(argv[-1]).write_bytes(b"")
        if argv[0] == "tar":
            Path(argv[argv.index("-czf") + 1]).write_bytes(b"x")
        if argv[0] == "rmdir":
            os.rmdir(argv[1])
        return subprocess.CompletedProcess(argv, 0, "", "")

    def names(self):
        return [c[0] + (" " + c[1] if c[0] == "systemctl" else "") for c in self.cmds]


def test_create_idempotent_and_files(tmp_path, monkeypatch):
    fs = FakeSystem(monkeypatch)
    lay = lay_of(tmp_path)
    enable(lay.tenants)
    s = tenant_admin.Sys(out=lambda *_: None, runner=fs.runner)
    tenant_admin.create(lay, s, "demo", title="Кафе «Ромашка»", jurisdiction="nl", budget=2.5)
    p = tenants.paths("demo", lay.tenants)
    assert "useradd" in fs.names() and "mkfs.ext4" in fs.names() and "mount" in fs.names()
    assert lay.fstab.read_text().count("demo.img") == 1 and list(lay.etc_backup.iterdir())
    for rel, (mode, _g) in tenants.LAYOUT.items():
        assert (p["base"] / rel).stat().st_mode & 0o7777 == mode, rel
    assert p["secrets"].stat().st_mode & 0o777 == 0o600 and json.loads(p["secrets"].read_text()) == {}
    t = tenants.load("demo", lay.tenants)
    assert t["title"] == "Кафе «Ромашка»" and t["jurisdiction"] == "NL" and t["budget_usd"] == 2.5
    assert t["profile"] == "openrouter"
    assert json.loads(p["audit"].read_text().splitlines()[0])["event"] == "create"
    assert (lay.systemd / "pult_t_demo.slice").exists() and (lay.systemd / "pult-share-demo.timer").exists()
    # повтор — ничего не пересоздаёт: ни пользователя, ни образа, ни строки fstab; юнит тот же — без просьбы перезапуска
    fs.cmds.clear()
    said = []
    s.out = said.append
    tenant_admin.create(lay, s, "demo")
    assert not any("Служба пространства изменилась" in x for x in said)
    # юнит старой версии (с RestrictSUIDSGID) — create его перепишет и попросит перезапустить службу
    sv = lay.units("demo")["service"]
    sv.write_text(sv.read_text().replace("LockPersonality=yes", "RestrictSUIDSGID=yes\nLockPersonality=yes"))
    said.clear()
    tenant_admin.create(lay, s, "demo")
    assert "RestrictSUIDSGID" not in sv.read_text()
    assert any("systemctl restart pult_t_demo.service" in x for x in said)
    fs.cmds.clear()
    tenant_admin.create(lay, s, "demo")
    assert not {"useradd", "mkfs.ext4", "fallocate", "mount"} & set(fs.names())
    assert lay.fstab.read_text().count("demo.img") == 1
    assert tenants.load("demo", lay.tenants)["budget_usd"] == 2.5 and tenants.load("demo", lay.tenants)["title"]


def test_create_needs_setup_and_valid_args(tmp_path):
    lay = lay_of(tmp_path)
    s = tenant_admin.Sys(out=lambda *_: None, runner=lambda *a, **k: pytest.fail("без настройки — ни одной команды"))
    with pytest.raises(SystemExit, match="настройка"):
        tenant_admin.create(lay, s, "demo")
    enable(lay.tenants)
    for kw in ({"size": "2T"}, {"jurisdiction": "RU", "profile": "openrouter"}, {"persona": "hacker"},
               {"profile": "claude"}):
        with pytest.raises(ValueError):
            tenant_admin.create(lay, s, "demo", **kw)
    with pytest.raises(ValueError):
        tenant_admin.create(lay, s, "Demo!")


def test_meta_jurisdiction_change_resets_profile():
    m = tenant_admin.meta_of(None, "demo", jurisdiction="NL", profile="deepseek")
    assert m["profile"] == "deepseek"
    assert tenant_admin.meta_of(m, "demo", jurisdiction="RU")["profile"] == "gigachat"


def test_destroy_backup_first_then_trash_then_purge(tmp_path, monkeypatch):
    fs = FakeSystem(monkeypatch)
    lay = lay_of(tmp_path)
    enable(lay.tenants)
    s = tenant_admin.Sys(out=lambda *_: None, runner=fs.runner)
    tenant_admin.create(lay, s, "demo")
    fs.cmds.clear()
    with pytest.raises(SystemExit, match="Не подтверждено"):
        tenant_admin.destroy(lay, s, "demo", yes="other")
    assert fs.cmds == []                                                  # без подтверждения — ничего
    monkeypatch.setattr(tenant_admin.shutil, "move", lambda a, b: os.replace(a, b))
    entry = tenant_admin.destroy(lay, s, "demo", yes="demo")
    names = fs.names()
    assert names.index("tar") < names.index("systemctl disable") < names.index("umount")    # сначала бэкап
    assert "userdel" not in names and "rm" not in names                    # ничего не удалено
    assert (entry / "demo.img").exists() and (entry / "pult_t_demo.service").exists()
    assert "demo.img" not in lay.fstab.read_text() and not lay.image("demo").exists()
    assert json.loads((entry / "info.json").read_text())["backup"].endswith(".tar.gz")
    assert any(c[:2] == ["usermod", "--lock"] for c in fs.cmds)
    fs.cmds.clear()
    with pytest.raises(SystemExit):
        tenant_admin.purge(lay, s, entry.name, yes="nope")
    assert fs.cmds == []
    with pytest.raises(SystemExit):
        tenant_admin.purge(lay, s, "../etc", yes="demo")
    tenant_admin.purge(lay, s, entry.name, yes="demo")
    assert ["userdel", "pult_t_demo"] in fs.cmds and ["rm", "-rf", "--one-file-system", str(entry)] in fs.cmds


def test_key_writes_tenant_files_only(tmp_path, monkeypatch):
    fs = FakeSystem(monkeypatch)
    lay = lay_of(tmp_path)
    enable(lay.tenants)
    s = tenant_admin.Sys(out=lambda *_: None, runner=fs.runner)
    tenant_admin.create(lay, s, "demo")
    owner_cfg = tmp_path / "owner-cfg"
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(owner_cfg))
    tenant_admin.set_key(lay, s, "demo", "deepseek", "sk-test-1234\n", default=True)
    p = tenants.paths("demo", lay.tenants)
    assert json.loads(p["secrets"].read_text()) == {"deepseek": "sk-test-1234"}
    st = json.loads((p["config_profiles"] / "deepseek.json").read_text())
    assert st["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-test-1234" and "deepseek" in st["env"]["ANTHROPIC_BASE_URL"]
    assert (p["config_profiles"] / "deepseek.json").stat().st_mode & 0o777 == 0o600
    assert tenants.load("demo", lay.tenants)["profile"] == "deepseek"
    assert not owner_cfg.exists()                                         # ключи пульта не тронуты
    with pytest.raises(ValueError):
        tenant_admin.set_key(lay, s, "demo", "openrouter", "a b")


def test_key_ru_only_russian_with_gateway(tmp_path, monkeypatch):
    fs = FakeSystem(monkeypatch)
    lay = lay_of(tmp_path)
    enable(lay.tenants)
    s = tenant_admin.Sys(out=lambda *_: None, runner=fs.runner)
    tenant_admin.create(lay, s, "ru", jurisdiction="RU")
    with pytest.raises(ValueError):
        tenant_admin.set_key(lay, s, "ru", "openrouter", "k" * 20)
    with pytest.raises(ValueError, match="шлюз"):
        tenant_admin.set_key(lay, s, "ru", "gigachat", "k" * 20)
    tenant_admin.set_key(lay, s, "ru", "gigachat", "k" * 20, base_url="https://gw.example:8090")
    env = json.loads((tenants.paths("ru", lay.tenants)["config_profiles"] / "gigachat.json").read_text())["env"]
    assert env["ANTHROPIC_BASE_URL"] == "https://gw.example:8090"


def test_login_warns_and_never_copies(tmp_path, monkeypatch):
    fs = FakeSystem(monkeypatch)
    lay = lay_of(tmp_path)
    enable(lay.tenants)
    out = []
    s = tenant_admin.Sys(out=out.append, runner=fs.runner)
    tenant_admin.create(lay, s, "ru", jurisdiction="RU")
    with pytest.raises(SystemExit, match="недоступен"):
        tenant_admin.login(lay, s, "ru", yes="да")
    tenant_admin.create(lay, s, "demo", jurisdiction="NL")
    fs.cmds.clear()
    with pytest.raises(SystemExit):
        tenant_admin.login(lay, s, "demo", yes="нет")
    assert not tenants.load("demo", lay.tenants).get("claude_login")
    out.clear()
    tenant_admin.login(lay, s, "demo", yes="да")
    assert any(tenants.LOGIN_WARNING in o for o in out) and any("только для ваших тестов" in o for o in out)
    assert tenants.load("demo", lay.tenants)["claude_login"] is True
    assert fs.cmds == []                                                   # ничего не скопировано и не запущено
    tenant_admin.create(lay, s, "demo", profile="claude")                  # теперь можно выбрать «claude»
    tenant_admin.logout(lay, s, "demo")
    t = tenants.load("demo", lay.tenants)
    assert not t.get("claude_login") and t["profile"] == "openrouter"


def test_cli_dry_run_and_root_check(tmp_path, capsys):
    assert tenant_admin.main(["--dry-run", "--srv", str(tmp_path / "s"), "--etc", str(tmp_path / "e"),
                              "create", "demo"]) == 0
    assert "useradd" in capsys.readouterr().out and not (tmp_path / "s").exists()
    if os.geteuid() != 0:
        assert tenant_admin.main(["--srv", str(tmp_path / "s"), "--etc", str(tmp_path / "e"), "create", "demo"]) == 2
    assert tenant_admin.main(["--dry-run", "create", "Bad!"]) == 2


def test_bin_pult_tenant_help():
    r = subprocess.run([sys.executable, str(ROOT / "bin/pult-tenant"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "destroy" in r.stdout


# --- bin/pult-tenant-setup (bash) ---------------------------------------------------------------------------------

SETUP = ROOT / "bin/pult-tenant-setup"


def test_setup_script_syntax_and_strict_mode():
    text = SETUP.read_text()
    assert "set -euo pipefail" in text and os.access(SETUP, os.X_OK)
    assert subprocess.run(["bash", "-n", str(SETUP)]).returncode == 0
    assert "NOPASSWD: $tmux\n" in text and "(%$GROUP_TENANTS)" in text and " ALL\n" not in text
    assert "visudo" in text and "hidepid=invisible" in text and "hidepid-off" in text


@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("getent"), reason="getent и stat -c — Linux")
def test_setup_dry_run_touches_nothing(tmp_path):
    import pwd
    me = pwd.getpwuid(os.getuid()).pw_name
    r = subprocess.run(["bash", str(SETUP), "install", "--owner", me, "--dry-run"], capture_output=True, text=True,
                       env={**os.environ, "TMPDIR": str(tmp_path)})
    if me == "root":
        assert r.returncode == 1
        return
    assert r.returncode == 0, r.stderr
    assert "sudoers.d/gas-pult-tenants" in r.stdout and "NOPASSWD" in r.stdout and "сухой прогон" in r.stdout
    assert list(tmp_path.iterdir()) == []                                  # временный файл убран
    r = subprocess.run(["bash", str(SETUP), "install", "--owner", "root", "--dry-run"], capture_output=True, text=True)
    assert r.returncode == 1 and "не root" in r.stderr
    r = subprocess.run(["bash", str(SETUP), "nope"], capture_output=True, text=True)
    assert r.returncode == 2


def test_create_budget_period_and_legacy(tmp_path, monkeypatch):
    """Задача 35: pult-tenant create … --budget 4 --period 30 --day-cap 3 → budget.json с нормой, периодом, началом и
    потолком дня; повтор без флагов — прежние значения; старый budget.json ({"daily_usd": 3}) читается."""
    from datetime import date
    fs = FakeSystem(monkeypatch)
    lay = lay_of(tmp_path)
    enable(lay.tenants)
    s = tenant_admin.Sys(out=lambda *_: None, runner=fs.runner)
    tenant_admin.create(lay, s, "demo", budget=4, period=30, day_cap=3, start="2026-11-02")
    p = tenants.paths("demo", lay.tenants)
    assert json.loads(p["budget"].read_text()) == {"daily_usd": 4.0, "period_days": 30, "start": "2026-11-02",
                                                   "day_cap_x": 3.0}
    tenant_admin.create(lay, s, "demo")                                  # повтор — всё как было
    assert json.loads(p["budget"].read_text())["start"] == "2026-11-02"
    tenant_admin.create(lay, s, "demo", day_cap=0)                       # 0 — потолок дня выключен
    assert json.loads(p["budget"].read_text())["day_cap_x"] is None
    assert "budget" not in json.loads(p["meta"].read_text())             # в описание пространства бюджет не пишем
    p["budget"].write_text('{"daily_usd": 3}')                          # старый вид
    t = tenants.load("demo", lay.tenants)
    assert t["budget_usd"] == 3 and t["budget"]["period_days"] == 30 and t["budget"]["start"] == date.today()
    for bad in ({"period": 0}, {"day_cap": 0.5}, {"start": "вчера"}):
        with pytest.raises(ValueError):
            tenant_admin.create(lay, s, "demo", **bad)
