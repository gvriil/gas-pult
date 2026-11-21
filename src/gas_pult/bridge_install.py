"""Мост к браузеру: установка одной командой (владелец 21.11, вариант «А» из docs/BRIDGE-INSTALL.md).

Панель показывает человеку одну команду:

- Mac, Linux: ``curl -fsSL '<панель>/api/bridge/install.sh?c=<КОД>' | bash``
- Windows:    ``irm '<панель>/api/bridge/install.ps1?c=<КОД>' | iex``

Сервер отдаёт скрипт с подставленными адресом панели и кодом пары (тем же одноразовым кодом на 10 минут). Скрипт:
скачивает официальный Node 22 (LTS) с nodejs.org в папку пользователя и сверяет SHA256 по ``SHASUMS256.txt``; кладёт
мост с панели; делает пару; ставит автозапуск без прав администратора (Mac — ``~/Library/LaunchAgents``, Linux —
``systemd --user``, Windows — ярлык в папке «Автозагрузка»); запускает мост и открывает страницу расширения Playwright в
Chrome или Edge. Повторный запуск обновляет Node и мост и заменяет прежнюю запись компьютера в панели. Удаление —
та же команда с ``?do=remove``.

Честно: подпись SHASUMS256.txt (GPG) не проверяется — сумма и архив берутся с nodejs.org по HTTPS.
"""

from __future__ import annotations

import re

from gas_pult.bridge import _CODE

NODE_MAJOR = 22
EXT_URL = "https://chromewebstore.google.com/detail/playwright-extension/mmlmfjhmonkocbjadbfplnigmagldckm"
_PANEL = re.compile(r"^https?://(?:[A-Za-z0-9-]+\.)*[A-Za-z0-9-]+(?::\d{1,5})?$")


def panel_ok(url: str) -> str:
    """Адрес панели для подстановки в скрипт: только схема, имя и порт (без кавычек, пробелов и пути)."""
    u = str(url or "").rstrip("/")
    if not _PANEL.match(u):
        raise ValueError("неверный адрес панели")
    return u


def commands(panel: str, code: str = "") -> dict:
    """Команды для человека: установить (с кодом) и удалить — Mac/Linux и Windows."""
    p = panel_ok(panel)
    q = f"?c={code}" if code else ""
    return {"mac": f"curl -fsSL '{p}/api/bridge/install.sh{q}' | bash",
            "win": f"irm '{p}/api/bridge/install.ps1{q}' | iex",
            "mac_remove": f"curl -fsSL '{p}/api/bridge/install.sh?do=remove' | bash",
            "win_remove": f"irm '{p}/api/bridge/install.ps1?do=remove' | iex"}


def script(kind: str, panel: str, code: str = "", remove: bool = False, valid: bool = True) -> str:
    """Текст ``install.sh`` (``kind="sh"``) или ``install.ps1`` (``"ps1"``). ``valid=False`` — код устарел: скрипт
    только скажет это человеку и ничего не поставит."""
    p = panel_ok(panel)
    code = str(code or "").strip().upper()
    if not remove and not _CODE.match(code):
        valid = False
    tpl = SH if kind == "sh" else PS1
    if not remove and not valid:
        tpl = SH_EXPIRED if kind == "sh" else PS1_EXPIRED
    c = commands(p)
    return (tpl.replace("__PANEL__", p).replace("__CODE__", code if valid and not remove else "")
            .replace("__MODE__", "remove" if remove else "install").replace("__MAJOR__", str(NODE_MAJOR))
            .replace("__EXT__", EXT_URL).replace("__REMOVE_SH__", c["mac_remove"])
            .replace("__REMOVE_PS__", c["win_remove"]))


SH_EXPIRED = """#!/usr/bin/env bash
printf '\\nКод в команде устарел или уже использован (код действует 10 минут, один раз).\\n'
printf 'Откройте панель → «Компьютеры» → «Подключить компьютер» и скопируйте команду заново.\\n\\n'
exit 1
"""

PS1_EXPIRED = """& {
  Write-Host ''
  Write-Host 'Код в команде устарел или уже использован (код действует 10 минут, один раз).' -ForegroundColor Yellow
  Write-Host 'Откройте панель → «Компьютеры» → «Подключить компьютер» и скопируйте команду заново.'
}
"""

SH = r"""#!/usr/bin/env bash
# Мост пульта к браузеру: установка одной командой (Mac, Linux). Без прав администратора.
# Скрипт сделан панелью: адрес панели и одноразовый код пары подставлены. Повторный запуск — обновление.
# Удалить мост: __REMOVE_SH__
set -euo pipefail
PANEL='__PANEL__'
CODE='__CODE__'
MODE='__MODE__'
MAJOR='__MAJOR__'
EXT='__EXT__'
LABEL='com.gas-pult.bridge'
[ -n "${HOME:-}" ] || { echo "нет папки пользователя (HOME)"; exit 1; }
DIR="$HOME/.gas-pult-bridge"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UNIT="$HOME/.config/systemd/user/gas-pult-bridge.service"

say() { printf '%s\n' "$*"; }
fail() { printf '\nНе получилось: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" != "0" ] || fail "запустите от своего пользователя, не от администратора (root)"

case "$(uname -s)" in Darwin) plat=darwin ;; Linux) plat=linux ;; *) fail "эта система не поддерживается" ;; esac
case "$(uname -m)" in
  arm64|aarch64) cpu=arm64 ;; x86_64|amd64) cpu=x64 ;; *) fail "этот процессор не поддерживается" ;;
esac

stop_bridge() {
  if [ "$plat" = darwin ]; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
  elif command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now gas-pult-bridge.service 2>/dev/null || true
  fi
  pkill -f "$DIR/gas-pult-bridge.mjs" 2>/dev/null || true
}

if [ "$MODE" = remove ]; then
  stop_bridge
  rm -f "$PLIST" "$UNIT" "$HOME/.gas-pult-bridge.json"
  rm -rf "$DIR"
  say ""
  say "Готово: мост удалён с этого компьютера."
  say "В панели уберите компьютер из списка: «Компьютеры» → компьютер → «Отозвать»."
  exit 0
fi

say ""
say "Подключаю компьютер к пульту. Это займёт 1–3 минуты."
mkdir -p "$DIR"
chmod 700 "$DIR"
SUMS="$DIR/SHASUMS256.txt"
trap 'rm -f "$SUMS" "$DIR/node.tgz" "$DIR/gas-pult-bridge.mjs.new"' EXIT

say "Шаг 1 из 4: Node.js $MAJOR с nodejs.org (со сверкой контрольной суммы)…"
BASE="https://nodejs.org/dist/latest-v$MAJOR.x"
curl -fsSL --retry 3 --proto '=https' -o "$SUMS" "$BASE/SHASUMS256.txt" || fail "не скачал список Node — нет интернета?"
LINE="$(grep -E "^[0-9a-f]{64}  node-v$MAJOR\.[0-9]+\.[0-9]+-$plat-$cpu\.tar\.gz$" "$SUMS" | head -n 1 || true)"
[ -n "$LINE" ] || fail "на nodejs.org нет Node $MAJOR для $plat-$cpu"
WANT="${LINE%% *}"
FILE="${LINE##* }"
VER="${FILE%-$plat-$cpu.tar.gz}"
if [ -x "$DIR/node/bin/node" ] && [ "$(cat "$DIR/node/VERSION" 2>/dev/null || true)" = "$VER" ]; then
  say "  $VER уже стоит"
else
  curl -fsSL --retry 3 --proto '=https' -o "$DIR/node.tgz" "$BASE/$FILE" || fail "не скачал Node"
  if command -v shasum >/dev/null 2>&1; then GOT="$(shasum -a 256 "$DIR/node.tgz" | cut -d' ' -f1)"
  else GOT="$(sha256sum "$DIR/node.tgz" | cut -d' ' -f1)"; fi
  [ "$GOT" = "$WANT" ] || fail "контрольная сумма Node (SHA256) не совпала — файл повреждён или подменён; не ставлю"
  rm -rf "$DIR/node.new"
  mkdir -p "$DIR/node.new"
  tar -xzf "$DIR/node.tgz" -C "$DIR/node.new" --strip-components 1
  printf '%s\n' "$VER" > "$DIR/node.new/VERSION"
  stop_bridge
  rm -rf "$DIR/node"
  mv "$DIR/node.new" "$DIR/node"
  say "  $VER — сумма SHA256 совпала"
fi
NODE="$DIR/node/bin/node"

say "Шаг 2 из 4: мост с панели…"
curl -fsSL --retry 3 -o "$DIR/gas-pult-bridge.mjs.new" "$PANEL/api/bridge/bridge.mjs" || fail "не скачал мост с панели"
stop_bridge
mv "$DIR/gas-pult-bridge.mjs.new" "$DIR/gas-pult-bridge.mjs"

say "Шаг 3 из 4: привязываю компьютер к пульту…"
"$NODE" "$DIR/gas-pult-bridge.mjs" pair "$PANEL" "$CODE" >/dev/null ||
  fail "не привязал — код устарел? Получите новый в панели"

say "Шаг 4 из 4: автозапуск при входе в систему…"
AUTO=1
if [ "$plat" = darwin ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$NODE</string><string>$DIR/gas-pult-bridge.mjs</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>WorkingDirectory</key><string>$HOME</string>
  <key>StandardOutPath</key><string>$DIR/bridge.log</string>
  <key>StandardErrorPath</key><string>$DIR/bridge.log</string>
</dict></plist>
EOF
  launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST" || fail "macOS не запустил мост"
elif command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  mkdir -p "$(dirname "$UNIT")"
  cat > "$UNIT" <<EOF
[Unit]
Description=Мост пульта к браузеру
[Service]
ExecStart="$NODE" "$DIR/gas-pult-bridge.mjs"
Restart=always
RestartSec=30
[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now gas-pult-bridge.service
else
  nohup "$NODE" "$DIR/gas-pult-bridge.mjs" >> "$DIR/bridge.log" 2>&1 &
  AUTO=0
fi

if [ "$plat" = darwin ]; then
  open -a "Google Chrome" "$EXT" 2>/dev/null || open -a "Microsoft Edge" "$EXT" 2>/dev/null ||
    open "$EXT" 2>/dev/null || true
else
  xdg-open "$EXT" >/dev/null 2>&1 || true
fi

say ""
if [ "$AUTO" = 1 ]; then
  say "Готово! Компьютер подключён к пульту. Мост запускается сам при входе в систему."
else
  say "Готово! Компьютер подключён к пульту. Автозапуска нет (нет systemd): после перезагрузки запустите команду снова."
fi
say "Осталось одно: в Chrome открылась страница «Playwright Extension» — нажмите «Установить»."
say "(Уже стоит — просто закройте вкладку.) Это окно можно закрыть."
say ""
say "Удалить мост: __REMOVE_SH__"
"""

PS1 = r"""# Мост пульта к браузеру: установка одной командой (Windows 10, 11). Без прав администратора.
# Скрипт сделан панелью: адрес панели и одноразовый код пары подставлены. Повторный запуск — обновление.
# Удалить мост: __REMOVE_PS__
& {
  $ErrorActionPreference = 'Stop'
  $ProgressPreference = 'SilentlyContinue'
  try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
  $Panel = '__PANEL__'
  $Code = '__CODE__'
  $Mode = '__MODE__'
  $Major = '__MAJOR__'
  $Ext = '__EXT__'
  $Dir = Join-Path $env:LOCALAPPDATA 'gas-pult-bridge'
  $Lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'gas-pult-bridge.lnk'
  $Mjs = Join-Path $Dir 'gas-pult-bridge.mjs'
  $NodeDir = Join-Path $Dir 'node'
  $Node = Join-Path $NodeDir 'node.exe'

  function Stop-Bridge {
    Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -like '*gas-pult-bridge.mjs*' } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  }

  try {
    if ($Mode -eq 'remove') {
      Stop-Bridge
      Remove-Item $Lnk -Force -ErrorAction SilentlyContinue
      Remove-Item $Dir -Recurse -Force -ErrorAction SilentlyContinue
      Remove-Item (Join-Path $HOME '.gas-pult-bridge.json') -Force -ErrorAction SilentlyContinue
      Write-Host ''
      Write-Host 'Готово: мост удалён с этого компьютера.' -ForegroundColor Green
      Write-Host 'В панели уберите компьютер из списка: «Компьютеры» → компьютер → «Отозвать».'
      return
    }
    Write-Host ''
    Write-Host 'Подключаю компьютер к пульту. Это займёт 1–3 минуты.'
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    $cpu = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }

    Write-Host "Шаг 1 из 4: Node.js $Major с nodejs.org (со сверкой контрольной суммы)…"
    $base = "https://nodejs.org/dist/latest-v$Major.x"
    $sums = [string](Invoke-RestMethod -UseBasicParsing "$base/SHASUMS256.txt")
    $line = $sums -split "`n" | ForEach-Object { $_.Trim() } |
      Where-Object { $_ -match "^[0-9a-f]{64}  node-v$Major\.\d+\.\d+-win-$cpu\.zip$" } | Select-Object -First 1
    if (-not $line) { throw "на nodejs.org нет Node $Major для Windows $cpu" }
    $want, $file = $line -split '\s+'
    $ver = $file -replace "-win-$cpu\.zip$", ''
    $verFile = Join-Path $NodeDir 'VERSION'
    if ((Test-Path $Node) -and ((Get-Content $verFile -ErrorAction SilentlyContinue) -eq $ver)) {
      Write-Host "  $ver уже стоит"
    } else {
      $zip = Join-Path $Dir 'node.zip'
      Invoke-WebRequest -UseBasicParsing "$base/$file" -OutFile $zip
      $got = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
      if ($got -ne $want.ToLower()) {
        Remove-Item $zip -Force
        throw 'контрольная сумма Node не совпала (SHA256) — файл повреждён или подменён; ничего не установлено'
      }
      $tmp = Join-Path $Dir 'node.new'
      Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
      Expand-Archive -Path $zip -DestinationPath $tmp -Force
      Stop-Bridge
      Remove-Item $NodeDir -Recurse -Force -ErrorAction SilentlyContinue
      Move-Item (Join-Path $tmp ($file -replace '\.zip$', '')) $NodeDir
      Remove-Item $tmp, $zip -Recurse -Force -ErrorAction SilentlyContinue
      Set-Content -Path $verFile -Value $ver
      Write-Host "  $ver — сумма SHA256 совпала"
    }

    Write-Host 'Шаг 2 из 4: мост с панели…'
    Invoke-WebRequest -UseBasicParsing "$Panel/api/bridge/bridge.mjs" -OutFile "$Mjs.new"
    Stop-Bridge
    Move-Item "$Mjs.new" $Mjs -Force

    Write-Host 'Шаг 3 из 4: привязываю компьютер к пульту…'
    & $Node $Mjs pair $Panel $Code | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'не привязал — код устарел? Получите новый в панели' }

    Write-Host 'Шаг 4 из 4: автозапуск при входе в Windows…'
    $sh = New-Object -ComObject WScript.Shell
    $l = $sh.CreateShortcut($Lnk)
    $l.TargetPath = $Node
    $l.Arguments = '"' + $Mjs + '"'
    $l.WorkingDirectory = $HOME
    $l.WindowStyle = 7
    $l.Description = 'Мост пульта к браузеру'
    $l.Save()
    Start-Process -FilePath $Node -ArgumentList ('"' + $Mjs + '"') -WorkingDirectory $HOME -WindowStyle Minimized

    $browser = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
                 "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
                 "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
                 "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
                 "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
      Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($browser) { Start-Process -FilePath $browser -ArgumentList $Ext } else { Start-Process $Ext }

    Write-Host ''
    Write-Host 'Готово! Компьютер подключён к пульту. Мост запускается сам при входе в Windows.' -ForegroundColor Green
    Write-Host 'Осталось одно: в Chrome или Edge открылась страница «Playwright Extension» — нажмите «Установить».'
    Write-Host '(Уже стоит — просто закройте вкладку.) Окно моста свёрнуто в панели задач — не закрывайте его.'
    Write-Host ''
    Write-Host 'Удалить мост: __REMOVE_PS__'
  } catch {
    Write-Host ''
    Write-Host ('Не получилось: ' + $_.Exception.Message) -ForegroundColor Red
  }
}
"""
