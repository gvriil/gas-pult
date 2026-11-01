"""Каталог голосов и их установка в ``<data>/voices`` (Piper) и ``<data>/silero`` (Silero)."""

from __future__ import annotations

import importlib.util
import shutil
import urllib.request
from pathlib import Path

from gas_pult.config import data_dir

PIPER_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU"
PIPER = {"irina": "Ирина", "dmitri": "Дмитрий", "denis": "Денис", "ruslan": "Руслан"}
SILERO_URL = "https://models.silero.ai/models/tts/ru/v5_ru.pt"
SILERO = {"xenia": "Ксения", "baya": "Бая", "kseniya": "Ксения-2", "aidar": "Айдар", "eugene": "Евгений"}


# Порядок карточек на экране «Голос» и в боте (/voice): сначала Silero, затем Piper.
ORDER = ["xenia", "baya", "aidar", "eugene", "kseniya", "irina", "dmitri", "denis", "ruslan"]
# Подпись карточки одним словом — пол голоса.
KIND = {"xenia": "женский", "baya": "женский", "aidar": "мужской", "eugene": "мужской", "kseniya": "женский",
        "irina": "женский", "dmitri": "мужской", "denis": "мужской", "ruslan": "мужской"}
PREVIEW = "Привет! Так я буду читать ответы Claude."      # фраза «Послушать»


def label(name: str) -> str:
    return PIPER.get(name) or SILERO.get(name) or name


def piper_model(name: str) -> Path:
    return data_dir() / "voices" / f"ru_RU-{name}-medium.onnx"


def silero_model() -> Path:
    return data_dir() / "silero" / "v5_ru.pt"


def has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


# Лицензия только для некоммерческого использования (Silero — CC BY-NC-SA): владельцу лично, если разрешено в
# config.toml (``personal_voices``); остальным людям и в установках для клиентов — скрыты.
NONCOMMERCIAL = frozenset(SILERO)


def installed(personal: bool = False) -> list[str]:
    """Установленные голоса. ``personal`` — показать и некоммерческие (Silero): только владельцу при
    ``personal_voices = true``; по умолчанию — нет."""
    out = [n for n in PIPER if piper_model(n).exists() and has("piper")]
    if personal and silero_model().exists() and has("torch"):
        out += list(SILERO)
    return out


def _fetch(url: str, dst: Path, log=print):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    log(f"  ↓ {url}")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    tmp.replace(dst)


def install(name: str, log=print):
    if name in PIPER:
        if not has("piper"):
            raise RuntimeError('Нет Piper: pip install "gas-pult[voice]"')
        m = piper_model(name)
        for p in (m, m.with_name(m.name + ".json")):
            if not p.exists():
                _fetch(f"{PIPER_HF}/{name}/medium/{p.name}", p, log)
    elif name in SILERO or name == "silero":
        if not has("torch"):
            raise RuntimeError('Нет torch: pip install "gas-pult[silero]" (см. README — колёса для CPU)')
        if not silero_model().exists():
            _fetch(SILERO_URL, silero_model(), log)
    else:
        raise RuntimeError(f"Неизвестный голос «{name}». Есть: {', '.join([*PIPER, *SILERO])}")


def cards(personal: bool = False, owner: bool = False) -> list[dict]:
    """Карточки локальных голосов в порядке ``ORDER``. Silero — только при ``personal`` (иначе их нет вовсе);
    не установленные — только владельцу, с командой установки; остальным — только установленные."""
    have = set(installed(personal))
    out = []
    for n in ORDER:
        if n in NONCOMMERCIAL and not personal:
            continue
        ok = n in have
        if ok or owner:
            out.append({"id": n, "name": label(n), "kind": KIND.get(n, ""), "ok": ok,
                        "why": "" if ok else "не установлен", "install": "" if ok else f"gas-pult voices install {n}"})
    return out
