"""Автотест изоляции (задача 25, часть B). В CI — моком: пользователей пространств нет, runuser и nsenter не
вызываются. Сама проба (PROBE) проверяется по-настоящему — на папках и сокете без прав у текущего пользователя."""

import json
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

from gas_pult import tenant_admin, tenant_check, tenants

as_root = pytest.mark.skipif(os.geteuid() == 0, reason="root читает всё — отказа не будет")


def load_probe():
    ns = {"__name__": "probe"}
    exec(tenant_check.PROBE, ns)
    return ns["probe"]


@pytest.fixture
def short_tmp():
    """Сокет AF_UNIX — до ~104 знаков пути: на macOS tmp_path длиннее."""
    d = tempfile.mkdtemp(prefix="gp-", dir="/tmp")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@as_root
def test_probe_real_denials(short_tmp):
    tmp_path = short_tmp
    probe = load_probe()
    closed = tmp_path / "closed"
    closed.mkdir()
    (closed / "secret").write_text("x")
    sock_path = closed / "s"
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(sock_path))
    srv.listen(1)
    own = tmp_path / "own.txt"
    own.write_text("ok")
    closed.chmod(0)
    try:
        res = probe([["list", str(closed)], ["read", str(closed / "secret")], ["connect", str(sock_path)],
                     ["see", "/proc/999999999"], ["read", "/proc/999999999/environ"], ["read", str(own)],
                     ["list", str(tmp_path)]])
    finally:
        closed.chmod(0o700)
        srv.close()
    assert res == ["denied"] * 5 + ["allowed", "allowed"]


def test_probe_reachable_socket_without_server_is_not_denial(short_tmp):
    tmp_path = short_tmp
    probe = load_probe()
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(tmp_path / "s"))
    s.close()                                     # файл сокета есть, сервера нет — путь достижим
    assert probe([["connect", str(tmp_path / "s")]]) == ["error:ConnectionRefusedError"]


def test_probe_runs_as_script(tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    r = subprocess.run(["python3", "-I", "-c", tenant_check.PROBE, json.dumps([["read", str(f)]])],
                       capture_output=True, text=True)
    assert json.loads(r.stdout) == ["allowed"]


# --- проверка целиком, моком ----------------------------------------------------------------------------------------

def world(tmp_path):
    root = tmp_path / "tenants"
    for slug in ("a", "b"):
        p = tenants.paths(slug + "x", root)
        for k in ("home", "config_claude_projects", "run_tmux"):
            p[k].mkdir(parents=True, exist_ok=True)
        for k in ("meta", "secrets", "audit", "socket"):
            p[k].write_text("{}")
    home = tmp_path / "owner"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude/.credentials.json").write_text("{}")
    return root, home


class Runner:
    """Мок runuser/nsenter: отвечает так, как ответила бы проба; ``leak`` — какие пути «доступны» из A."""

    def __init__(self, leak=(), control_ok=True, broken=False):
        self.calls, self.leak, self.control_ok, self.broken = [], set(leak), control_ok, broken

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if self.broken:
            return subprocess.CompletedProcess(argv, 1, "", "runuser: user pult_t_ax does not exist")
        items = json.loads(argv[-1])
        res = []
        for _kind, path in items:
            if path.endswith("/ax/home"):
                res.append("allowed" if self.control_ok else "denied")
            else:
                res.append("allowed" if any(x in path for x in self.leak) else "denied")
        return subprocess.CompletedProcess(argv, 0, json.dumps(res) + "\n", "")


def fake_exists(p) -> bool:
    """Процессы B и владельца в моке «есть»; файлы — как на диске."""
    return str(p).startswith("/proc/") or os.path.exists(p)


def run(tmp_path, runner, **kw):
    root, home = world(tmp_path)
    out = []
    args = {"service_pid": 4242, "b_pids": [501, 502], "owner_pids": [100], "hidepid": True,
            "exists": fake_exists} | kw
    code = tenant_check.check("ax", "bx", root, home, runner, out=out.append, **args)
    return code, out[0]


def test_all_denied_ok(tmp_path):
    r = Runner()
    code, text = run(tmp_path, r)
    assert code == 0 and "ПРОВАЛ: 0" in text and "изоляция в порядке" in text
    assert "прочитать secrets.json B" in text and "окружение процесса B 501" in text
    assert "подключиться к сокету tmux B" in text and ".credentials.json" in text
    sandbox, plain = r.calls
    assert sandbox[:5] == ["nsenter", "-t", "4242", "-m", "--"] and sandbox[5:8] == ["runuser", "-u", "pult_t_ax"]
    assert plain[:3] == ["runuser", "-u", "pult_t_ax"]                 # без песочницы — права файлов


@pytest.mark.parametrize("leak", ["/bx/secrets.json", "/owner", "/proc/501/environ", "/bx/run/tmux/default",
                                  "/bx/config/claude", "/proc/100/environ"])
def test_any_leak_fails(tmp_path, leak):
    code, text = run(tmp_path, Runner(leak={leak}))
    assert code == 1 and "ДОСТУП ЕСТЬ" in text and "ИЗОЛЯЦИЯ НАРУШЕНА" in text


def test_visible_process_without_hidepid_is_warning_in_plain_only(tmp_path):
    code, text = run(tmp_path, Runner(leak={"/proc/501"}), hidepid=False)
    rows = [ln for ln in text.splitlines() if "увидеть процесс B 501" in ln]
    # /proc/501/environ тоже «доступен» в моке — значит, ПРОВАЛ; отдельно видимость: в окне A — ПРОВАЛ, без hidepid —
    # ВНИМАНИЕ
    assert code == 1
    assert any(ln.startswith(tenant_check.SANDBOX) and "ПРОВАЛ" in ln for ln in rows)
    assert any(ln.startswith(tenant_check.PLAIN) and "ВНИМАНИЕ" in ln for ln in rows)


def test_only_visibility_without_hidepid_passes_with_warning(tmp_path):
    class SeeOnly(Runner):
        def __call__(self, argv, **kw):
            r = super().__call__(argv, **kw)
            items = json.loads(argv[-1])
            res = json.loads(r.stdout)
            if argv[0] == "runuser":                                     # без песочницы процесс виден
                res = ["allowed" if k == "see" else v for (k, _), v in zip(items, res, strict=True)]
            return subprocess.CompletedProcess(argv, 0, json.dumps(res), "")
    code, text = run(tmp_path, SeeOnly(), hidepid=False)
    assert code == 0 and "ВНИМАНИЕ: 2" in text
    code, text = run(tmp_path, SeeOnly(), hidepid=True)                  # с hidepid видимость обязательна
    assert code == 1


def test_control_failure_and_broken_probe_fail(tmp_path):
    code, text = run(tmp_path, Runner(control_ok=False))
    assert code == 1 and "контроль не прошёл" in text
    code, text = run(tmp_path, Runner(broken=True))
    assert code == 1 and "проба не ответила" in text


def test_missing_targets_and_stopped_service_fail(tmp_path):
    code, text = run(tmp_path, Runner(), service_pid=None, b_pids=[])
    assert code == 1 and "служба tmux пространства A" in text and "ни одного не найдено" in text
    root, home = world(tmp_path / "w2")
    tenants.paths("bx", root)["socket"].unlink()
    out = []
    assert tenant_check.check("ax", "bx", root, home, Runner(), 1, [5], [], True, fake_exists, out=out.append) == 1
    assert "не проверено" in out[0]


def test_same_or_bad_slug(tmp_path):
    with pytest.raises(ValueError):
        tenant_check.check("ax", "ax", tmp_path, None, Runner())
    with pytest.raises(ValueError):
        tenant_check.check("ax", "../b", tmp_path, None, Runner())


def test_pids_of_and_hidepid(tmp_path):
    for pid, uid in ((10, 1000), (11, 2000), (12, 2000)):
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "status").write_text(f"Name:\tx\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
    (tmp_path / "self").mkdir()
    assert tenant_check.pids_of(2000, tmp_path) == [11, 12] and tenant_check.pids_of(3, tmp_path) == []
    m = tmp_path / "mounts"
    m.write_text("proc /proc proc rw,nosuid,relatime,hidepid=invisible,gid=999 0 0\n")
    assert tenant_check.hidepid_on(m)
    m.write_text("proc /proc proc rw,nosuid,relatime 0 0\n")
    assert not tenant_check.hidepid_on(m)


def test_cli_check_needs_root(tmp_path, capsys):
    if os.geteuid() == 0:
        pytest.skip("под root проверка пошла бы по-настоящему")
    assert tenant_admin.main(["--srv", str(tmp_path), "check", "ax", "bx"]) == 2
    assert "root" in capsys.readouterr().err


def test_main_bad_input(tmp_path, capsys):
    assert tenant_check.main(Path(tmp_path), "ax", "Bad!") == 2
    assert tenant_check.main(Path(tmp_path), "ax", "no-such-tenant-zz") == 2       # нет пользователя B
