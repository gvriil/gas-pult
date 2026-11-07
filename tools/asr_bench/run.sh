#!/bin/sh
# Запуск одного движка с замером пиковой памяти: run.sh <имя-результата> <venv> <скрипт> [аргументы…]
#   tools/asr_bench/run.sh whisper-large-v3-turbo whisper eng_whisper.py --model large-v3-turbo
# Пиковая память (Maximum resident set size) дописывается в results/<имя>.json полем rss_mb.
# Движки запускать строго по одному: на сервере пульта мало свободной памяти. Процесс идёт в отдельной
# группе systemd с потолком памяти ASR_MEM_MAX (по умолчанию 2000M) без свопа: не влез — убит, службы не страдают.
set -eu
name=$1; venv=$2; script=$3; shift 3
here=$(cd "$(dirname "$0")" && pwd)
data=${ASR_BENCH_DATA:-$HOME/.local/share/asr-bench}
mkdir -p "$data/results" "$data/tmp"
export HF_HOME="$data/hf" TMPDIR="$data/tmp"
log="$data/results/$name.time"
cap=${ASR_MEM_MAX:-2000M}
if command -v systemd-run >/dev/null && [ "$cap" != "0" ]; then
  set -- systemd-run --user --scope -q -p "MemoryMax=$cap" -p MemorySwapMax=0 "$data/$venv/bin/python" "$here/$script" "$@"
else
  set -- "$data/$venv/bin/python" "$here/$script" "$@"
fi
/usr/bin/time -v -o "$log" "$@"
rss=$(awk -F': ' '/Maximum resident set size/ {print int($2/1024)}' "$log")
python3 - "$data/results/$name.json" "$rss" <<'EOF'
import json, sys
p, rss = sys.argv[1], int(sys.argv[2])
d = json.load(open(p)); d["rss_mb"] = rss
json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
print(f"{p}: rss {rss} МБ")
EOF
