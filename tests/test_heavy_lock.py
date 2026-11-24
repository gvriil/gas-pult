"""Один тяжёлый прогон на сервер (tests/heavy_lock.py): второй ждёт первого, по таймауту — ошибка, в CI замка нет."""

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = ("import sys, time, heavy_lock; heavy_lock.hold('pytest', 'проба'); print('got', flush=True); "
        "time.sleep(float(sys.argv[1]))")


def _env(tmp_path, **kw):
    env = {k: v for k, v in os.environ.items() if k not in ("CI", "GAS_PULT_TEST_LOCK", "GAS_PULT_HEAVY_LOCK_HELD")}
    env.update(XDG_RUNTIME_DIR=str(tmp_path), PYTHONPATH=str(HERE), **kw)
    return env


def _run(tmp_path, hold_s, **kw):
    return subprocess.Popen([sys.executable, "-c", CODE, str(hold_s)], env=_env(tmp_path, **kw),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_second_waits_then_times_out(tmp_path):
    a = _run(tmp_path, 3)
    assert a.stdout.readline().strip() == "got"
    b = _run(tmp_path, 0, GAS_PULT_TEST_LOCK_WAIT="0.5")
    out, err = b.communicate(timeout=20)
    assert b.returncode != 0 and "got" not in out
    assert "жду: идёт другой тяжёлый прогон" in err and "проба" in err and "TimeoutError" in err
    a.kill()
    a.wait()
    # ядро сняло flock вместе с процессом — следующий проходит сразу
    c = _run(tmp_path, 0)
    out, _ = c.communicate(timeout=20)
    assert c.returncode == 0 and "got" in out


def test_off_in_ci(tmp_path):
    a = _run(tmp_path, 3)
    assert a.stdout.readline().strip() == "got"
    t = time.monotonic()
    b = _run(tmp_path, 0, CI="true", GAS_PULT_TEST_LOCK_WAIT="0.5")
    out, _ = b.communicate(timeout=20)
    a.kill()
    a.wait()
    assert b.returncode == 0 and "got" in out and time.monotonic() - t < 5


def test_child_does_not_wait_for_parent(tmp_path):
    """e2e держит замок и запускает дочерний процесс (панель), который тоже берёт замок — без взаимной блокировки."""
    child = f"import subprocess, sys; subprocess.run([sys.executable, '-c', {CODE!r}, '0'], check=True)"
    code = f"import heavy_lock; heavy_lock.hold('pytest'); {child}"
    r = subprocess.run([sys.executable, "-c", code], env=_env(tmp_path, GAS_PULT_TEST_LOCK_WAIT="1"),
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and "got" in r.stdout, r.stderr
