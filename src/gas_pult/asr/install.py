"""``gas-pult asr install``: служба распознавания в своей папке ``<данные пульта>/asr`` — воспроизводимо.

1. venv ``asr/venv`` тем же Python, что запускает команду (или ``--python``), пакеты — ``requirements.txt`` рядом
   (точные версии: onnxruntime, numpy). Временные файлы pip — в ``asr/tmp`` на диске: ``/tmp`` здесь бывает в ОЗУ.
2. Модель T-one ``asr/model/model.onnx`` — с Hugging Face по закреплённой ревизии, проверка sha256 (или ``--model``:
   готовый файл, например из кеша замера, — с той же проверкой).
3. Юнит ``~/.config/systemd/user/gas-pult-asr.service`` из шаблона ``gas-pult-asr.service`` рядом: потолок памяти
   ``MemoryMax=1G`` без свопа — служба при превышении перезапускается, а не выдавливает пульт в своп.
   ``--enable`` — сразу включить и запустить; без него — только напечатать команду.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from importlib import resources
from pathlib import Path

import gas_pult
from gas_pult import asr

REVISION = "106f3b0b32a9e107eb613312e4ebc61ff3d53926"          # t-tech/T-one на Hugging Face
MODEL_URL = f"https://huggingface.co/t-tech/T-one/resolve/{REVISION}/model.onnx"
MODEL_SHA256 = "707e4a282d5036304a0b8603ad83945840c3075f53c49911ef88c19bcc5a7d52"
THREADS = 2                                                     # потоков onnxruntime на распознавание


def unit_path() -> Path:
    return Path.home() / ".config/systemd/user" / asr.UNIT


def unit_text(python: Path, src: Path, sock: Path, model: Path, threads: int = THREADS) -> str:
    tpl = resources.files("gas_pult.asr").joinpath("gas-pult-asr.service").read_text(encoding="utf-8")
    return tpl.format(python=python, src=src, socket=sock, model=model, threads=threads)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def fetch_model(dest: Path, src: Path | None = None, url: str = MODEL_URL, digest: str = MODEL_SHA256) -> str:
    """Модель на место с проверкой sha256. Уже лежит правильная — ничего не делаем. → что сделано."""
    if dest.exists() and sha256(dest) == digest:
        return "модель уже на месте"
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    try:
        if src:
            shutil.copyfile(src, part)
            how = f"модель скопирована из {src}"
        else:
            with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            how = "модель скачана с Hugging Face"
        if (got := sha256(part)) != digest:
            raise ValueError(f"контрольная сумма модели не та: {got[:12]}…, ждали {digest[:12]}…")
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return how


def systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], check=check, capture_output=True, text=True)


def install(python: str | None = None, model: Path | None = None, enable: bool = False, say=print) -> None:
    root = asr.home()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)                                       # сокет и модель — только владельцу
    venv, tmp = root / "venv", root / "tmp"
    py = venv / "bin" / "python"
    if not py.exists():
        say(f"• venv: {venv}")
        subprocess.run([python or sys.executable, "-m", "venv", str(venv)], check=True)
    tmp.mkdir(exist_ok=True)
    req = resources.files("gas_pult.asr").joinpath("requirements.txt")
    with resources.as_file(req) as rp:
        say("• пакеты: onnxruntime, numpy")
        subprocess.run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", str(rp)],
                       check=True, env={**os.environ, "TMPDIR": str(tmp)})
    shutil.rmtree(tmp, ignore_errors=True)
    dest = root / "model" / "model.onnx"
    say("• " + fetch_model(dest, model))
    src = Path(gas_pult.__file__).resolve().parent.parent     # откуда взят пакет: боевая копия или venv
    unit = unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(unit_text(py, src, asr.socket_path(), dest))
    systemctl("daemon-reload")
    say(f"• юнит: {unit} (MemoryMax=1G, без свопа)")
    if not enable:
        return say(f"Готово. Включить: systemctl --user enable --now {asr.UNIT}")
    systemctl("enable", "--now", asr.UNIT)
    systemctl("restart", asr.UNIT)
    for _ in range(60):                                         # модель грузится 3–4 с
        if st := asr.status():
            return say(f"✓ служба работает: {st}")
        time.sleep(0.5)
    say(f"! служба не ответила за 30 с: journalctl --user -u {asr.UNIT} -n 30")


def uninstall(say=print) -> None:
    systemctl("disable", "--now", asr.UNIT, check=False)
    unit_path().unlink(missing_ok=True)
    systemctl("daemon-reload", check=False)
    say(f"✓ служба удалена; venv и модель остались в {asr.home()} — их можно удалить вручную")
