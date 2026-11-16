"""Основной скрипт панели разбирается без ошибок (16.11: второе `const tok` в #243 — SyntaxError, панель не грузилась
ни в одном браузере; открытые вкладки работали, поэтому сбой заметили по iPhone). Части `js/*.js` — тоже."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"


def main_script() -> str:
    s = (WEB / "index.html").read_text(encoding="utf-8")
    i = s.index("<script>\n", s.index('id="secretRules"'))
    return s[i + len("<script>\n"):s.index("</script>", i)]


@pytest.mark.skipif(not shutil.which("node"), reason="нет node")
def test_core_and_parts_parse():
    srcs = {"index.html": main_script()} | {f"js/{p.name}": p.read_text(encoding="utf-8")
                                            for p in sorted((WEB / "js").glob("*.js"))}
    # ядро — обычный скрипт (new Function: повторное const/let — ошибка); части — ES-модули (vm.SourceTextModule нет
    # без флага — проверяем как модуль через --input-type=module --check)
    for name, src in srcs.items():
        if name == "index.html":
            code = ("try { new Function(require('fs').readFileSync(0, 'utf8')); } "
                    "catch (e) { console.log(e.message); process.exit(1); }")
            r = subprocess.run(["node", "-e", code], input=src, capture_output=True, text=True, timeout=60)
        else:
            r = subprocess.run(["node", "--input-type=module", "--check"], input=src, capture_output=True, text=True,
                               timeout=60)
        assert r.returncode == 0, f"{name}: {(r.stdout or r.stderr).strip()[:300]}"


def test_no_duplicate_top_level_const():
    """Без node: верхнеуровневые const/let ядра не повторяются (то, что сломало панель 16.11). Повтор function — не
    ошибка синтаксиса (действует последний), его ловит не этот тест."""
    import re
    names = re.findall(r"^(?:const|let)\s+([A-Za-z_$][\w$]*)", main_script(), re.M)
    dup = sorted({n for n in names if names.count(n) > 1})
    assert not dup, "повторные объявления верхнего уровня: " + json.dumps(dup, ensure_ascii=False)
