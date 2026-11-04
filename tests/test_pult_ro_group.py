"""Группа pult-ro у бота и панели (rogroup.py, bin/pult-tenant-setup status, gas-pult doctor, service install).

Ничего системного: группы, sg/newgrp, systemctl и exec — подменой; /proc — поддельная папка.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from gas_pult import cli, rogroup

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "bin/pult-tenant-setup"
GID = 973


def fake_group(monkeypatch, members=("owner",), exists=True):
    g = SimpleNamespace(gr_name="pult-ro", gr_gid=GID, gr_mem=list(members))
    monkeypatch.setattr(rogroup, "group", lambda name="pult-ro": g if exists else None)
    monkeypatch.setattr(rogroup, "me", lambda: "owner")
    return g


def which_of(**tools):
    return lambda name: tools.get(name)


def runner_of(version="newgrp from util-linux 2.41.3", ids=f"{GID} 1001 27 100", rc=0, calls=None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append(cmd)
        if cmd[-1] == "--version":
            return subprocess.CompletedProcess(cmd, 0, version, "")
        if "id -G" in " ".join(cmd):
            return subprocess.CompletedProcess(cmd, rc, ids + "\n", "")
        if cmd[:2] == ["systemctl", "--user"]:
            return subprocess.CompletedProcess(cmd, 0, {"gas-pult.service": "41\n",
                                                        "gas-pult-webapp.service": "42\n"}[cmd[-1]], "")
        raise AssertionError(cmd)
    return run


# --- обёртка ------------------------------------------------------------------------------------------------------

def test_tool_prefers_sg_and_accepts_only_util_linux_newgrp():
    assert rogroup.tool(which_of(sg="/usr/bin/sg", newgrp="/usr/bin/newgrp"), runner_of()) == ("sg", "/usr/bin/sg")
    assert rogroup.tool(which_of(newgrp="/usr/bin/newgrp"), runner_of()) == ("newgrp", "/usr/bin/newgrp")
    # newgrp из shadow не умеет -c — не годится
    assert rogroup.tool(which_of(newgrp="/usr/bin/newgrp"), runner_of(version="newgrp: group '--version' does not "
                                                                           "exist")) is None
    assert rogroup.tool(which_of(), runner_of()) is None


def test_wrap_runs_same_command_with_exec():
    cmd = ["/opt/py env/bin/python", "-m", "gas_pult", "run"]
    sg = rogroup.wrap(cmd, ("sg", "/usr/bin/sg"))
    assert sg == ["/usr/bin/sg", "pult-ro", "-c", "exec '/opt/py env/bin/python' -m gas_pult run"]
    ng = rogroup.wrap(cmd, ("newgrp", "/usr/bin/newgrp"))
    assert ng == ["/usr/bin/newgrp", "-c", "exec '/opt/py env/bin/python' -m gas_pult run", "pult-ro"]


def test_exec_start_with_group_and_as_before_without():
    cmd = ["/home/u/.local/share/gas-pult/env/bin/python", "-m", "gas_pult", "run"]
    assert rogroup.exec_start(cmd, None) == " ".join(cmd)                        # группы нет — как раньше
    line = rogroup.exec_start(cmd, ("newgrp", "/usr/bin/newgrp"))
    assert line == f'/usr/bin/newgrp -c "exec {" ".join(cmd)}" pult-ro'
    assert rogroup.sd_quote("50%") == '"50%%"' and rogroup.sd_quote('a"$b') == '"a\\"$$b"'


# --- regain: перезапуск процесса с группой ------------------------------------------------------------------------

def test_regain_execs_once_through_wrapper(monkeypatch):
    fake_group(monkeypatch)
    monkeypatch.setattr(rogroup, "has", lambda gid: False)
    calls, execs = [], []
    r = rogroup.regain(["/py", "-m", "gas_pult", "webapp", "--url", "https://x"], env={"PATH": "/usr/bin"},
                       execve=lambda *a: execs.append(a), runner=runner_of(calls=calls),
                       which=which_of(newgrp="/usr/bin/newgrp"), log=lambda m: None)
    assert r == "exec" and len(execs) == 1
    path, argv, env = execs[0]
    assert path == "/usr/bin/newgrp" and argv[-1] == "pult-ro"
    assert argv[2] == "exec /py -m gas_pult webapp --url https://x"
    assert env == {"PATH": "/usr/bin", rogroup.ENV: "1"}                         # второй раз — не пробовать
    assert any("id -G" in " ".join(c) for c in calls)                            # сначала пробный запуск


@pytest.mark.parametrize("case, expect", [("again", "again"), ("no-group", "no-group"), ("stranger", "not-member"),
                                          ("has", "has"), ("no-tool", "no-tool"), ("probe-fails", "failed"),
                                          ("probe-no-gid", "failed")])
def test_regain_otherwise_runs_as_before(monkeypatch, case, expect):
    fake_group(monkeypatch, members=("someone",) if case == "stranger" else ("owner",), exists=case != "no-group")
    monkeypatch.setattr(rogroup, "has", lambda gid: case == "has")
    if case == "stranger":
        import pwd
        monkeypatch.setattr(pwd, "getpwnam", lambda u: SimpleNamespace(pw_gid=1001))
    env = {rogroup.ENV: "1"} if case == "again" else {}
    runner = runner_of(rc=1 if case == "probe-fails" else 0, ids="1001 27 100" if case == "probe-no-gid" else
                       f"{GID} 1001")
    which = which_of() if case == "no-tool" else which_of(sg="/usr/bin/sg")
    logs = []
    r = rogroup.regain(["/py"], env=env, execve=lambda *a: pytest.fail("перезапуска быть не должно"),
                       runner=runner, which=which, log=logs.append)
    assert r == expect
    if case in ("no-tool", "probe-fails"):
        assert logs and "pult-ro" in logs[0]


def test_cli_run_and_webapp_regain_others_do_not(monkeypatch):
    seen = []
    monkeypatch.setattr(rogroup, "regain", lambda *a, **k: seen.append("regain") or "has")
    for name in ("cmd_run", "cmd_webapp", "cmd_doctor"):
        monkeypatch.setattr(cli, name, lambda a, n=name: seen.append(n))
    # main сравнивает fn с cli.cmd_run / cli.cmd_webapp — подменённые функции попадают и в парсер
    cli.main(["run"])
    cli.main(["webapp"])
    cli.main(["doctor"])
    assert seen == ["regain", "cmd_run", "regain", "cmd_webapp", "cmd_doctor"]


# --- doctor -------------------------------------------------------------------------------------------------------

def fake_proc(tmp, pid, groups, gid_line="1001\t1001\t1001\t1001", cmd=b"python\0-m\0gas_pult\0run\0"):
    d = tmp / str(pid)
    d.mkdir(parents=True)
    (d / "status").write_text(f"Name:\tpython\nUid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n"
                              f"Gid:\t{gid_line}\nGroups:\t{groups}\n")
    (d / "cmdline").write_bytes(cmd)


def test_proc_has_reads_groups_and_effective_gid(tmp_path):
    fake_proc(tmp_path, 1, "27 100 1001 ")
    fake_proc(tmp_path, 2, f"27 {GID} 1001 ")
    fake_proc(tmp_path, 3, "27 100 1001 ", gid_line=f"1001\t{GID}\t{GID}\t{GID}")         # после newgrp/sg
    assert rogroup.proc_has(1, GID, tmp_path) is False
    assert rogroup.proc_has(2, GID, tmp_path) is True
    assert rogroup.proc_has(3, GID, tmp_path) is True
    assert rogroup.proc_has(9, GID, tmp_path) is None


def test_doctor_checks_say_pult_has_no_group(monkeypatch, tmp_path):
    fake_group(monkeypatch)
    fake_proc(tmp_path, 41, "27 100 1001 ")                              # бот — без группы (как 04.11)
    fake_proc(tmp_path, 42, f"{GID} 1001 ")                              # панель — с группой
    out = rogroup.checks(runner=runner_of(), which=which_of(sg="/usr/bin/sg"), proc=tmp_path)
    bad = [c for c in out if not c[1]]
    assert len(bad) == 1 and bad[0][0] == "у пульта нет группы pult-ro (gas-pult, PID 41)"
    assert "restart" in bad[0][2]
    assert ("gas-pult-webapp: группа pult-ro есть", True, "") in out
    # нечем сменить группу — подсказка про пакет
    out = rogroup.checks(runner=runner_of(), which=which_of(), proc=tmp_path)
    assert ("обёртка группы pult-ro: нет", False, rogroup.HINT_TOOL) in out
    assert "util-linux-extra" in rogroup.HINT_TOOL


def test_doctor_checks_silent_without_group(monkeypatch):
    fake_group(monkeypatch, exists=False)
    assert rogroup.checks(runner=lambda *a, **k: pytest.fail("systemctl не нужен")) == []


# --- gas-pult service install -------------------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform == "darwin", reason="юнит systemd — Linux")
@pytest.mark.parametrize("wrap", [None, ("newgrp", "/usr/bin/newgrp")])
def test_service_install_unit(monkeypatch, tmp_path, wrap, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(rogroup, "ready", lambda: (SimpleNamespace(gr_gid=GID, gr_mem=["owner"]) if wrap else None,
                                                  wrap))
    ran = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **k: ran.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, "Linger=yes", ""))
    cli.cmd_service(SimpleNamespace(action="install"))
    text = (tmp_path / ".config/systemd/user" / cli.UNIT).read_text()
    start = next(line for line in text.splitlines() if line.startswith("ExecStart="))
    plain = " ".join(cli._python_cmd())
    if wrap:
        assert start == f'ExecStart=/usr/bin/newgrp -c "exec {plain}" pult-ro'
        assert "группой pult-ro" in capsys.readouterr().out
    else:
        assert start == f"ExecStart={plain}"                              # группы нет — как раньше
    assert "KillMode=process" in text
    assert all(c[0] == "systemctl" or c[0] == "loginctl" for c in ran)


# --- bin/pult-tenant-setup status ---------------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("getent"), reason="getent — Linux")
def test_setup_status_reports_pult_without_group(tmp_path):
    import grp
    import pwd
    mine = grp.getgrgid(os.getgid())                                     # любая существующая группа вместо pult-ro
    gid = mine.gr_gid
    fake_proc(tmp_path, 41, "27 100 ", gid_line="5000\t5000\t5000\t5000")                       # бот без группы
    fake_proc(tmp_path, 42, f"27 {gid} ", gid_line="5000\t5000\t5000\t5000",
              cmd=b"python\0-m\0gas_pult\0webapp\0--url\0https://x\0")                         # панель с группой
    fake_proc(tmp_path, 43, "", cmd=b"bash\0")                                                 # не пульт
    me = pwd.getpwuid(os.getuid()).pw_name
    r = subprocess.run(["bash", str(SETUP), "status", "--owner", me], capture_output=True, text=True,
                       env={**os.environ, "PULT_GROUP_RO": mine.gr_name, "PULT_PROC": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    assert f"✗ у пульта нет группы {mine.gr_name} (бот, PID 41)" in r.stdout
    assert f"✓ пульт (webapp, PID 42): группа {mine.gr_name} есть" in r.stdout
    assert "PID 43" not in r.stdout
