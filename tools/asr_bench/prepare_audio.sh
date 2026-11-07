#!/bin/sh
# Подготовка аудио для замера: <папка с .ogg/.oga/.mp3> → audio/<n>.wav (16 кГц) и audio/8k/<n>.wav (8 кГц для T-one).
#   tools/asr_bench/prepare_audio.sh ~/путь/к/голосовым
# Имена файлов — по порядку длительности не меняются: берётся имя исходника без расширения.
# Нужен ffmpeg: системный или из imageio-ffmpeg (FF=/путь/к/ffmpeg).
set -eu
src=$1
data=${ASR_BENCH_DATA:-$HOME/.local/share/asr-bench}
FF=${FF:-ffmpeg}
mkdir -p "$data/audio/8k"
chmod 700 "$data" "$data/audio"
for f in "$src"/*.ogg "$src"/*.oga "$src"/*.mp3; do
  [ -e "$f" ] || continue
  n=$(basename "${f%.*}")
  "$FF" -loglevel error -y -i "$f" -ac 1 -ar 16000 -sample_fmt s16 "$data/audio/$n.wav"
  "$FF" -loglevel error -y -i "$f" -ac 1 -ar 8000 -sample_fmt s16 "$data/audio/8k/$n.wav"
done
chmod 600 "$data"/audio/*.wav "$data"/audio/8k/*.wav
ls "$data/audio"
