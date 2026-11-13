"""CI (задача 36): прерванные задания macOS не блокируют PR и main.

Причина (по `gh run view` и аннотациям): «The job was not acquired by Runner of type hosted even after multiple
attempts … capacity constraints macOS arm64» — задание 15 минут ждёт раннер и отменяется без шагов; плюс прогоны
`push main` отменяли друг друга (concurrency по ref с cancel-in-progress). Без PyYAML — разбор текста файлов."""

import re
import shutil
import subprocess
from pathlib import Path

WF = Path(__file__).resolve().parents[1] / ".github/workflows"
PR_OS = "${{ fromJSON(github.event_name == 'pull_request' && '[\"ubuntu-latest\"]' || " \
        "'[\"ubuntu-latest\", \"macos-latest\"]') }}"


def jobs(text: str) -> dict[str, str]:
    """Задания: имя → текст его блока (два пробела отступа)."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z][\w-]*):\n", body, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_cancel_in_progress_only_for_pull_requests():
    ci = (WF / "ci.yml").read_text()
    assert "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n" in ci
    group = re.search(r"^  group: (.+)$", ci, re.M).group(1)
    assert "github.run_id" in group and "pull_request.number" in group          # main — своя группа у прогона
    assert "cancel-in-progress: true" not in ci


def test_every_job_has_timeout():
    for name in ("ci.yml", "ci-retry.yml"):
        js = jobs((WF / name).read_text())
        assert js
        for job, block in js.items():
            m = re.search(r"^    timeout-minutes: (\d+)$", block, re.M)
            assert m and 0 < int(m.group(1)) <= 30, (name, job)


def test_macos_not_in_pull_requests_but_daily_and_on_main():
    ci = (WF / "ci.yml").read_text()
    head = ci.split("\njobs:\n", 1)[0]
    assert "  push:\n    branches: [main]\n  pull_request:\n" in head
    assert re.search(r"^  schedule:\n    - cron: \"[\d*/ ,-]+\"", head, re.M) and "  workflow_dispatch:" in head
    js = jobs(ci)
    for job in ("test", "passkeys"):
        assert f"        os: {PR_OS}\n" in js[job], job
    for job in ("lint", "build"):
        assert "    runs-on: ubuntu-latest\n" in js[job]
    assert "macos-latest" not in ci.replace(PR_OS, "")       # macOS — только в матрице не для PR


def test_retry_once_only_runner_not_acquired():
    r = (WF / "ci-retry.yml").read_text()
    assert "  workflow_run:\n    workflows: [CI]\n    types: [completed]\n" in r
    assert "  actions: write\n" in r
    assert "github.event.workflow_run.run_attempt == 1" in r                       # один раз
    script = r.split("        run: |\n", 1)[1]
    script = "\n".join(line[10:] for line in script.splitlines())
    assert '.conclusion == "cancelled" and (.steps | length) == 0' in script      # только «раннер не взял»
    assert 'gh run rerun --job "$j"' in script and "--failed" not in script       # настоящие падения — не повторяем
    assert '"$head" != "$SHA"' in script                                         # новый пуш — не повторяем
    if shutil.which("bash"):
        assert subprocess.run(["bash", "-n"], input=script, text=True).returncode == 0


def test_browser_tests_run_in_ci_without_skips():
    """13.11: 25 браузерных тестов в CI молча пропускались — playwright не ставился. Теперь — задание «browser»."""
    js = jobs((WF / "ci.yml").read_text())
    b = js["browser"]
    assert '.[dev,browser]' in b and "playwright install --with-deps chromium" in b
    assert '! grep -E "SKIPPED.*(playwright' in b and "--cov=gas_pult" in b
    assert "browser" in re.search(r"needs: \[(.+)\]", js["build"]).group(1)
    pp = (WF.parents[1] / "pyproject.toml").read_text()
    assert re.search(r'^browser = \[.*"playwright>=', pp, re.M)
