#!/usr/bin/env bash
# gas-pult — установка одной командой (Linux / macOS).
#   ./install.sh [--silero] [--no-voice] [--no-service]
# Ставит пакет в отдельное окружение ~/.local/share/gas-pult/env, команду — в ~/.local/bin/gas-pult,
# затем: gas-pult init (токен и ваш ID) → голос → фоновая служба. Повторный запуск = обновление.
set -euo pipefail

REPO="${GAS_PULT_REPO:-https://github.com/gvriil/gas-pult}"
REF="${GAS_PULT_REF:-main}"
DATA="${GAS_PULT_DATA_DIR:-$HOME/.local/share/gas-pult}"
ENV="$DATA/env"
BIN="${GAS_PULT_BIN:-$HOME/.local/bin}"
VOICE=1 SILERO=0 SERVICE=1

for arg in "$@"; do
  case "$arg" in
    --silero) SILERO=1 ;;
    --no-voice) VOICE=0 ;;
    --no-service) SERVICE=0 ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "Неизвестный ключ: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1m▸ %s\033[0m\n' "$*"; }
die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- проверки ---
PY="$(command -v python3 || true)"
[ -n "$PY" ] || die "Нужен Python 3.11+ (Ubuntu: sudo apt install python3 python3-venv; macOS: brew install python)"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || die "Нужен Python 3.11+, а здесь $("$PY" -V)"
"$PY" -c 'import venv, ensurepip' 2>/dev/null || die "Нет модуля venv: sudo apt install python3-venv"
command -v tmux >/dev/null || die "Нужен tmux (Ubuntu: sudo apt install tmux; macOS: brew install tmux)"
command -v claude >/dev/null || [ -x "$BIN/claude" ] || \
  printf '\033[33m! Claude Code не найден в PATH — поставьте его: https://docs.claude.com/en/docs/claude-code\033[0m\n'

# --- откуда ставить: из клона или с GitHub ---
SRC="$REPO/archive/$REF.tar.gz"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$HERE" ] && grep -qs '^name = "gas-pult"' "$HERE/pyproject.toml"; then SRC="$HERE"; fi

EXTRAS=""
[ "$VOICE" = 1 ] && EXTRAS="voice"
[ "$SILERO" = 1 ] && EXTRAS="${EXTRAS:+$EXTRAS,}silero"

say "Окружение: $ENV"
mkdir -p "$DATA" "$BIN"
[ -x "$ENV/bin/python" ] || "$PY" -m venv "$ENV"
"$ENV/bin/python" -m pip install -q --upgrade pip
PIP_ARGS=()
# torch для CPU — без гигабайтов CUDA (на macOS обычное колесо и так без CUDA)
[ "$SILERO" = 1 ] && [ "$(uname)" = Linux ] && PIP_ARGS+=(--extra-index-url https://download.pytorch.org/whl/cpu)
say "Ставлю gas-pult${EXTRAS:+[$EXTRAS]} из $SRC"
"$ENV/bin/python" -m pip install -q --upgrade ${PIP_ARGS[@]+"${PIP_ARGS[@]}"} "gas-pult${EXTRAS:+[$EXTRAS]} @ ${SRC/#\//file:///}"
if [ -e "$BIN/gas-pult" ] && [ ! -L "$BIN/gas-pult" ]; then   # старый скрипт с тем же именем — не затираем
  mv "$BIN/gas-pult" "$BIN/gas-pult.bak-$(date +%Y%m%d%H%M%S)"
  printf '\033[33m! Прежний %s сохранён как .bak-*\033[0m\n' "$BIN/gas-pult"
fi
ln -sfn "$ENV/bin/gas-pult" "$BIN/gas-pult"
case ":$PATH:" in *":$BIN:"*) ;; *) printf '\033[33m! Добавьте %s в PATH (например, в ~/.bashrc)\033[0m\n' "$BIN" ;; esac

# --- настройка (только при первой установке) ---
if [ -s "${GAS_PULT_CONFIG_DIR:-$HOME/.config/gas-pult}/config.toml" ]; then
  say "Настройки уже есть — оставляю (перенастроить: gas-pult init)"
else
  "$ENV/bin/gas-pult" init </dev/tty   # при curl | bash stdin занят скриптом — спрашиваем с терминала
fi

if [ "$VOICE" = 1 ]; then
  say "Голос Ирина (Piper)"
  "$ENV/bin/gas-pult" voices install irina
  if [ "$SILERO" = 1 ]; then say "Голоса Silero"; "$ENV/bin/gas-pult" voices install silero; fi
fi

if [ "$SERVICE" = 1 ]; then
  say "Фоновая служба"
  "$ENV/bin/gas-pult" service install
fi

say "Проверка"
"$ENV/bin/gas-pult" doctor || true
printf '\n\033[32m✓ Готово.\033[0m Откройте своего бота в Telegram → /start\n'
