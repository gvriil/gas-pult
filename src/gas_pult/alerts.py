"""Сбои пульта — владельцу (разбор 22.11, docs/ALERTS.md): ночью 6×502 на /api/projects и красный CI ``main`` семь
слияний подряд — никто не узнал.

- ``beat`` — признак жизни: ``<данные>/heartbeat-bot`` и ``heartbeat-web`` (время), не чаще раза в минуту.
  Внешний сторож проверяет, что отметка свежая (сам сторож — вне репозитория).
- ``Watch.errors`` — сводка новых ``server_error`` (панель упала в обработчике) и ``js_error`` (ошибка JS в браузере)
  из журнала событий чата (``chatlog``). Не чаще раза в 30 минут на класс; без текстов и персональных данных:
  число, маршруты ``/api/…`` и классы исключений.
- ``main_ci`` и ``Watch.ci`` — последний законченный push-прогон CI в ``main`` (через ``gh``): красный — строка
  брифинга, а вне брифинга одно сообщение, если красный дольше часа (не чаще раза в 6 часов).
- ``Watch.connectors`` — квитанция владельцу о коннекторах: события ``connector_down`` / ``connector_up`` от сторожа
  ``connwatch`` (по одному на переход) — одним сообщением.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from gas_pult import store

BEAT_EVERY = 60                      # с: отметка жизни — не чаще раза в минуту
ERR_GAP = 30 * 60                    # с: сводка ошибок — не чаще раза в 30 минут на класс
CI_RED_AFTER = 60 * 60               # с: красный main дольше часа — сообщить
CI_GAP = 6 * 3600                    # с: и не чаще раза в 6 часов
CI_TTL = 300                         # с: ответ gh держим 5 минут (брифинг панели открывают часто)
CLASSES = {"server_error": "ошибки сервера", "js_error": "ошибки JS в браузере"}
REPO = Path(__file__).resolve().parents[2]      # проверка из исходников: gh берёт репозиторий из git remote
RUN = subprocess.run                 # тесты подменяют: без настоящего gh

_beats: dict[str, float] = {}
_lock = threading.Lock()


def beat(data: Path, name: str, now: float | None = None) -> bool:
    """Отметка жизни ``<данные>/heartbeat-<name>``: время Unix и ISO. Записана — True; чаще раза в минуту — False."""
    now = time.time() if now is None else now
    path = Path(data) / f"heartbeat-{name}"
    with _lock:
        if now - _beats.get(str(path), 0) < BEAT_EVERY:
            return False
        _beats[str(path)] = now
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(f"{int(now)} {datetime.fromtimestamp(now).isoformat(timespec='seconds')}\n")
        tmp.replace(path)
    except OSError:
        return False
    return True


_ID = re.compile(r"[\d@:]|[^/]{25,}")


def route(path: str) -> str:
    """Маршрут без данных: только ``/api/…``, не больше трёх частей, части с цифрами и длинные — «*»."""
    path = str(path or "").split("?", 1)[0]
    if not path.startswith("/api/"):
        return "страница"
    return "/" + "/".join("*" if _ID.search(p) else p for p in path.strip("/").split("/")[:3])


def summary(cls: str, evs: list[dict], minutes: int) -> str:
    """«⚠ Панель: ошибки сервера — 6 за 2 мин (/api/projects ×6; CalledProcessError)» — без текстов и ПД."""
    what: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for e in evs:
        if cls == "server_error":
            w = route(e.get("path", ""))
            k = re.sub(r"[^\w.]", "", str(e.get("exc") or ""))[:40]
        else:                                    # js_error: экран и тип; текст и место ошибки — не шлём
            w = re.sub(r"[^\w-]", "", str(e.get("screen") or ""))[:30] or "экран ?"
            k = re.sub(r"[^\w]", "", str(e.get("kind") or ""))[:30]
        what[w] = what.get(w, 0) + 1
        if k:
            kinds[k] = kinds.get(k, 0) + 1
    top = lambda d: ", ".join(f"{k} ×{n}" for k, n in sorted(d.items(), key=lambda x: -x[1])[:3])   # noqa: E731
    tail = "; ".join(x for x in (top(what), ", ".join(list(kinds)[:3])) if x)
    return f"⚠ Панель: {CLASSES[cls]} — {len(evs)} за {max(1, minutes)} мин ({tail})"


def main_ci(cwd: Path | None = None, now: float | None = None) -> dict | None:
    """Последний законченный push-прогон CI в ``main``: {red, since (Unix), job, url}. Нет gh или репозитория — None."""
    cwd = Path(cwd or REPO)
    now = time.time() if now is None else now
    hit = _ci_cache.get(str(cwd))
    if hit and now - hit[0] < CI_TTL:
        return hit[1]
    out = None
    if RUN is not None and (cwd / ".git").exists():
        try:
            out = _main_ci(cwd)
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
            out = None
    _ci_cache[str(cwd)] = (now, out)
    return out


_ci_cache: dict[str, tuple[float, dict | None]] = {}


def _gh(cwd: Path, *args) -> list | dict:
    r = RUN(["gh", *args], capture_output=True, text=True, timeout=30, cwd=str(cwd))
    if r.returncode != 0:
        raise OSError((r.stderr or "gh не ответил").strip()[:200])
    return json.loads(r.stdout)


def _ts(s: str) -> float:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


def _main_ci(cwd: Path) -> dict | None:
    runs = _gh(cwd, "run", "list", "-b", "main", "-w", "CI", "-e", "push", "-L", "30",
               "--json", "databaseId,conclusion,status,createdAt,updatedAt,url")
    done = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") not in ("cancelled", "skipped")]
    if not done:
        return None
    last = done[0]
    if last["conclusion"] == "success":
        return {"red": False, "url": last.get("url", "")}
    first = last                                   # с какого прогона main красный: подряд красные до зелёного
    for r in done[1:]:
        if r["conclusion"] == "success":
            break
        first = r
    jobs = _gh(cwd, "run", "view", str(last["databaseId"]), "--json", "jobs").get("jobs") or []
    job = next((j.get("name", "") for j in jobs if j.get("conclusion") == "failure"), "")
    return {"red": True, "since": _ts(first.get("updatedAt") or first["createdAt"]), "job": job[:80],
            "url": last.get("url", ""), "id": last["databaseId"]}


def ci_line(m: dict, now: float | None = None) -> str:
    """«CI main красный с 14:05: pytest (macos-latest, 3.12)» (дата — если не сегодня)."""
    t = datetime.fromtimestamp(m["since"])
    today = datetime.fromtimestamp(time.time() if now is None else now).date()
    when = t.strftime("%H:%M") if t.date() == today else t.strftime("%d.%m %H:%M")
    return f"CI main красный с {when}" + (f": {m['job']}" if m.get("job") else "")


class Watch:
    """Что уже сообщили: ``<данные>/alerts_state.json`` — до какого события прочитано и когда слали по классу."""

    def __init__(self, data: Path):
        self.path = Path(data) / "alerts_state.json"

    def load(self) -> dict:
        return store.load_json(self.path)

    def save(self, st: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        store.save_json(self.path, st)

    def errors(self, events, now: float | None = None) -> list[str]:
        """Сводки по классам, которые пора прислать. ``events`` — ``chatlog.Log``. Первый запуск — только запомнить
        «отсюда»: старое не присылаем. Ещё рано (30 минут не прошло) — события копятся до следующей сводки."""
        now = time.time() if now is None else now
        st = self.load()
        seen, sent = st.setdefault("seen", {}), st.setdefault("sent", {})
        out = []
        if not seen:
            st["seen"] = {c: now for c in CLASSES}
            self.save(st)
            return out
        evs = events.since(min(seen.get(c, now) for c in CLASSES), set(CLASSES))
        for cls in CLASSES:
            new = [e for e in evs if e.get("ev") == cls and e.get("ts", 0) > seen.get(cls, now)]
            if not new or now - sent.get(cls, 0) < ERR_GAP:
                continue
            first = min(e["ts"] for e in new)
            out.append(summary(cls, new, round((now - first) / 60)))
            seen[cls], sent[cls] = max(e["ts"] for e in new), now
        if out:
            self.save(st)
        return out

    def connectors(self, events, now: float | None = None) -> list[str]:
        """Квитанция о коннекторах (``connwatch``): новые ``connector_down`` / ``connector_up`` — одним сообщением.
        Сторож пишет событие только на переход — значит, одна квитанция на переход. Первый запуск — «отсюда»."""
        from gas_pult import connwatch

        now = time.time() if now is None else now
        st = self.load()
        seen = st.get("conn_seen")
        if seen is None:
            st["conn_seen"] = now
            self.save(st)
            return []
        evs = [e for e in events.since(seen, {"connector_down", "connector_up"}) if e.get("ts", 0) > seen]
        if not evs:
            return []
        st["conn_seen"] = max(e["ts"] for e in evs)
        self.save(st)
        return [connwatch.receipt(evs)]

    def ci(self, m: dict | None, now: float | None = None) -> str:
        """Сообщение о красном ``main``: красный дольше часа и раз в 6 часов не слали. Иначе — ""."""
        now = time.time() if now is None else now
        if not m or not m.get("red") or now - m["since"] < CI_RED_AFTER:
            return ""
        st = self.load()
        if now - st.get("ci_sent", 0) < CI_GAP:
            return ""
        st["ci_sent"] = now
        self.save(st)
        return f"⚠ {ci_line(m, now)}. {m.get('url', '')}".strip()
