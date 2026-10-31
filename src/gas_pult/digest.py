"""Утренняя сводка «ждёт владельца»: что стоит без решения — одним сообщением в Telegram.

- PR, открытые дольше ``STALE_DAYS`` дней или с красным CI, во всех репозиториях владельца на GitHub (``gh``);
- окна, где Claude ждёт ответа (меню или вопрос на экране);
- строки «Ждут «да»» в ``HANDOFF.md`` штабов (папки проектов, без рабочих копий git worktree).

У каждого пункта — «да» (слить PR / открыть экран / передать «да» в окно проекта, с подтверждением),
«закрыть» (убрать из сводок) и «позже» (вернётся завтра). Пусто — сводку не шлём.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

STALE_DAYS = 2
LATER = 20 * 3600                       # «позже» — до следующей утренней сводки
GONE = 30 * 86400                       # «закрыть» — убрать на месяц
WAIT = re.compile(r"[Жж]д(?:ут|ёт|ет)\s+«да»")
QUERY = ("query($q:String!){search(query:$q,type:ISSUE,first:50){nodes{... on PullRequest{number title url createdAt "
         "repository{nameWithOwner} mergeable commits(last:1){nodes{commit{statusCheckRollup{state}}}}}}}}")


def key(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def prs(owner: str, now: float) -> list[dict]:
    """Открытые PR владельца, которые ждут: старше STALE_DAYS дней или с красным CI."""
    r = subprocess.run(["gh", "api", "graphql", "-f", f"q=is:pr is:open user:{owner} archived:false",
                        "-f", f"query={QUERY}"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError((r.stderr.strip() or "gh не ответил")[:200])
    out = []
    for n in json.loads(r.stdout)["data"]["search"]["nodes"]:
        if not n:
            continue
        roll = ((n["commits"]["nodes"] or [{}])[0].get("commit") or {}).get("statusCheckRollup") or {}
        ci = roll.get("state", "")
        age = int((now - datetime.fromisoformat(n["createdAt"].replace("Z", "+00:00")).timestamp()) // 86400)
        if ci in ("FAILURE", "ERROR") or age >= STALE_DAYS:
            repo = n["repository"]["nameWithOwner"]
            out.append({"kind": "pr", "key": key("pr", repo, n["number"]), "repo": repo, "n": n["number"],
                        "title": n["title"], "url": n["url"], "age": age, "ci": ci,
                        "ok": ci in ("SUCCESS", "") and n["mergeable"] == "MERGEABLE"})
    return out


def handoffs(roots: list[Path]) -> list[dict]:
    """Строки «Ждут «да»» в HANDOFF.md штабов — с подпунктами под ними (до трёх)."""
    out, seen = [], set()
    for root in roots:
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            f = d / "HANDOFF.md"
            if (d / ".git").is_file() or not f.is_file():        # рабочая копия worktree — её штаб в основной папке
                continue
            lines = f.read_text(errors="replace").splitlines()
            for i, line in enumerate(lines):
                if not WAIT.search(line):
                    continue
                pad = len(line) - len(line.lstrip())
                sub = []
                for nxt in lines[i + 1:i + 4]:
                    if not nxt.strip() or len(nxt) - len(nxt.lstrip()) <= pad:
                        break
                    sub.append(nxt.strip().lstrip("-* ").strip())
                text = " ".join([line.strip().lstrip("-* ").strip(), *sub])[:300]
                if (d.name, text) not in seen:
                    seen.add((d.name, text))
                    out.append({"kind": "yes", "key": key("yes", d.name, text), "project": d.name, "path": str(d),
                                "text": text})
    return out


class Digest:
    """Состояние сводки: когда слали, что отложено, пункты последней сводки (для кнопок) — ``digest.json``."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict:
        try:
            return {"sent": "", "snooze": {}, "items": {}, **json.loads(self.path.read_text())}
        except (OSError, ValueError):
            return {"sent": "", "snooze": {}, "items": {}}

    def save(self, st: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False))
        tmp.chmod(0o600)
        tmp.replace(self.path)

    def due(self, at: str, now: datetime) -> bool:
        """Пора слать: время сводки наступило, а сегодня её ещё не было."""
        return bool(at) and now.strftime("%H:%M") >= at and self.load()["sent"] != now.strftime("%Y-%m-%d")

    def fresh(self, items: list[dict], now: float) -> list[dict]:
        """Без отложенных и закрытых; запоминает пункты для кнопок."""
        st = self.load()
        st["snooze"] = {k: t for k, t in st["snooze"].items() if t > now}
        items = [x for x in items if x["key"] not in st["snooze"]]
        st["items"] = {x["key"]: x for x in items}
        self.save(st)
        return items

    def mark_sent(self, day: str):
        st = self.load()
        st["sent"] = day
        self.save(st)

    def item(self, k: str) -> dict | None:
        return self.load()["items"].get(k)

    def snooze(self, k: str, seconds: int):
        st = self.load()
        st["snooze"][k] = time.time() + seconds
        self.save(st)


def cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def render(items: list[dict]) -> tuple[str, dict]:
    """Текст сводки и кнопки: строка на пункт — «да» · «закрыть» · «позже»."""
    lines, rows = ["☀️ Ждёт вашего решения:"], []
    for i, x in enumerate(items, 1):
        if x["kind"] == "pr":
            why = "CI красный" if x["ci"] in ("FAILURE", "ERROR") else f"открыт {x['age']} дн."
            lines.append(f"{i}. PR {x['repo']}#{x['n']} — {cut(x['title'], 70)} ({why})")
            yes = (f"{i} ✅ слить", f"dg:y:{x['key']}") if x["ok"] else None
            first = yes or {"text": f"{i} 🔗 открыть", "url": x["url"]}
        elif x["kind"] == "win":
            lines.append(f"{i}. Окно «{x['name']}» — Claude ждёт ответа")
            first = (f"{i} 📺 экран", f"dg:y:{x['key']}")
        else:
            lines.append(f"{i}. {x['project']}: {cut(x['text'], 160)}")
            first = (f"{i} ✅ да", f"dg:y:{x['key']}")
        rows.append([first, (f"{i} ✖️ закрыть", f"dg:c:{x['key']}"), (f"{i} ⏰ позже", f"dg:l:{x['key']}")])
    kbd = {"inline_keyboard": [[b if isinstance(b, dict) else {"text": b[0], "callback_data": b[1]} for b in r]
                               for r in rows]}
    return "\n".join(lines), kbd


def merge(repo: str, n: int) -> str:
    r = subprocess.run(["gh", "pr", "merge", str(n), "--repo", repo, "--squash", "--delete-branch"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError((r.stderr.strip() or "gh не слил")[:300])
    return f"✅ Слито: {repo}#{n}"
