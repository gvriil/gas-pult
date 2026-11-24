"""Мост: браузер для Playwright Extension (владелец 24.11 — Яндекс Браузер). Настройка browser в
~/.gas-pult-bridge.json; auto — Chrome, если в нём стоит расширение;
иначе — браузер, где оно есть; явный выбор — путь к исполняемому файлу."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

BRIDGE = Path(__file__).resolve().parents[1] / "bridge" / "gas-pult-bridge.mjs"
EXT = "mmlmfjhmonkocbjadbfplnigmagldckm"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="нет node")


def _env(home: Path) -> dict:
    return {"HOME": str(home), "PATH": "/usr/bin:/bin:" + str(Path(shutil.which("node")).parent)}


def js(home: Path, code: str):
    src = (f"const m = await import({json.dumps(BRIDGE.as_uri())});"
           f" console.log(JSON.stringify(await (async () => {{ {code} }})()));")
    r = subprocess.run(["node", "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30,
                       env=_env(home))
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_has_extension_by_folder_or_prefs(tmp_path):
    a = tmp_path / "A" / "Default" / "Extensions" / EXT
    a.mkdir(parents=True)
    b = tmp_path / "B" / "Profile 2"
    b.mkdir(parents=True)
    (b / "Preferences").write_text(json.dumps({"extensions": {"settings": {EXT: {}}}}))
    (tmp_path / "C" / "Default").mkdir(parents=True)
    dirs = ", ".join(f"m.hasExtension({json.dumps(str(tmp_path / x))})" for x in "ABC")
    got = js(tmp_path, f"return [{dirs}, m.hasExtension('/нет')];")
    assert got == [True, True, False, False]


def test_pick_explicit_and_auto(tmp_path):
    yx = "/Applications/Yandex.app/Contents/MacOS/Yandex"
    assert js(tmp_path, "return m.pickBrowser({browser: 'yandex'}, 'darwin', {});") == {"name": "yandex", "exe": yx}
    assert js(tmp_path, "return m.pickBrowser({browser: 'chrome'}, 'darwin', {});") == {"name": "chrome", "exe": ""}
    assert js(tmp_path, "return m.pickBrowser({}, 'darwin', {PLAYWRIGHT_MCP_EXECUTABLE_PATH: '/x/y'});") == \
        {"name": "свой путь", "exe": "/x/y"}
    (tmp_path / "Library/Application Support/Google/Chrome/Default/Extensions" / EXT).mkdir(parents=True)
    assert js(tmp_path, "return m.pickBrowser({}, 'darwin', {});") == {"name": "chrome", "exe": ""}


def test_browser_command_saves_choice(tmp_path):
    r = subprocess.run(["node", str(BRIDGE), "browser", "yandex"], capture_output=True, text=True, timeout=30,
                       env=_env(tmp_path))
    assert r.returncode == 0 and "yandex" in r.stdout, r.stderr
    assert json.loads((tmp_path / ".gas-pult-bridge.json").read_text())["browser"] == "yandex"
    bad = subprocess.run(["node", str(BRIDGE), "browser", "opera"], capture_output=True, text=True, timeout=30,
                         env=_env(tmp_path))
    assert bad.returncode == 2
