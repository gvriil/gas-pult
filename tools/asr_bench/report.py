"""Сводная таблица по результатам замера: WER по эталонам, скорость, задержка, память. Только stdlib.

    python3 tools/asr_bench/report.py                      # эталоны ~/.local/share/asr-bench/ref/<n>.txt
    python3 tools/asr_bench/report.py --draft-ref eleven-scribe_v2 --refs 03,07,09   # черновой эталон из движка

Эталон — ручная правка расшифровки (ref/<n>.txt). WER = (замены + вставки + пропуски) / слов эталона, после
нормализации: нижний регистр, ё→е, без пунктуации. Печатает таблицу в Markdown — её и вставляем в отчёт.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c


def fmt(x, nd=2, suffix=""):
    return "—" if x is None else f"{x:.{nd}f}{suffix}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--results", type=Path, default=c.RESULTS)
    p.add_argument("--ref", type=Path, default=c.REF)
    p.add_argument("--draft-ref", default="", help="записать ref/<n>.txt из результата этого движка (черновик)")
    p.add_argument("--refs", default="", help="какие записи взять в эталон: 03,07,09")
    a = p.parse_args()

    res = {}
    for f in sorted(a.results.glob("*.json")):
        d = json.loads(f.read_text())
        res[d["engine"]] = d

    if a.draft_ref:
        a.ref.mkdir(parents=True, exist_ok=True)
        for n in a.refs.split(","):
            out = a.ref / f"{n}.txt"
            if out.exists():
                print(f"{out} уже есть — не трогаю")
                continue
            out.write_text(res[a.draft_ref]["files"][n]["text"] + "\n")
            out.chmod(0o600)
            print(f"черновик {out} ← {a.draft_ref}")
        return

    refs = {f.stem: f.read_text() for f in sorted(a.ref.glob("*.txt"))}
    draft = (a.ref / "DRAFT").exists()
    print(f"Эталон: {', '.join(refs) or 'нет'}{' (ЧЕРНОВИК — предварительно)' if draft else ''}\n")
    print("| Движок | WER, % | RTF | Итог после конца, с (медиана / макс) | Первый текст, с (медиана) "
          "| Окно 10 с, с | Память, МБ |")
    print("|---|---|---|---|---|---|---|")
    for name, d in res.items():
        fs = d["files"]
        errs = words = 0
        for n, ref in refs.items():
            if n in fs:
                e, w = c.wer(ref, fs[n].get("text", ""))
                errs, words = errs + e, words + w
        w = 100 * errs / words if words else None
        rtf = sum(x["total_s"] for x in fs.values()) / sum(x["dur"] for x in fs.values())
        lag = sorted(x.get("final_lag_s", x.get("final_after_end_s")) for x in fs.values())
        firsts = sorted(x["first_partial_s"] for x in fs.values() if x.get("first_partial_s") is not None)
        med = firsts[len(firsts) // 2] if firsts else None
        win = d.get("window", {}).get("10")
        print(f"| {name} | {fmt(w, 1)} | {fmt(rtf, 3)} | {fmt(lag[len(lag) // 2])} / {fmt(lag[-1])} | {fmt(med)} "
              f"| {fmt(win)} | {d.get('rss_mb', '—')} |")


if __name__ == "__main__":
    main()
