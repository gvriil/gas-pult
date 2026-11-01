# Claude Code на сервере пульта: вход, если через пульт не получилось

Бот и панель запускаются и без Claude Code. Если Claude Code не установлен или вход не выполнен, `/start` в боте
и главная панели показывают мастер: «Войти в Claude», «Подключить интеграции», «Ключ провайдера», «Проверка».

**Обычный путь — через пульт.** «🔑 Войти в Claude» → пульт открывает отдельное окно tmux (сессия `<сессия>-setup`,
по умолчанию `main-setup`) с `claude auth login` → присылает ссылку → вы входите в аккаунт Claude в браузере
телефона или компьютера → копируете код со страницы → присылаете его боту (или вставляете в поле панели). Пульт
вставляет код в окно, проверяет `claude auth status` и закрывает окно.

Почему `claude auth login`, а не `claude setup-token`: `auth login` сохраняет вход в каталоге конфигурации Claude
(`~/.claude` или `CLAUDE_CONFIG_DIR`), и его видят все сессии пульта. `setup-token` только печатает токен —
его нужно положить в переменную окружения самому (вариант 2 ниже).

Если так не выходит (нет ссылки, страница не даёт код, вход не подтверждается) — один из вариантов ниже.
Проверка после любого из них: в боте «🩺 Проверка» или на сервере `gas-pult doctor`.

## 0. Установить Claude Code

На сервере, под тем же пользователем, под которым работает пульт:

```bash
curl -fsSL https://claude.ai/install.sh | bash      # или: npm install -g @anthropic-ai/claude-code
claude --version
```

Подробно — [документация Claude Code](https://docs.claude.com/en/docs/claude-code/setup). Убедитесь, что `claude`
виден службе пульта: `gas-pult service install` прописывает `PATH` с `~/.local/bin`; после установки перезапустите
службу (`systemctl --user restart gas-pult` или `launchctl kickstart -k gui/$UID/com.github.gvriil.gas-pult`).

## 1. Войти вручную на сервере (ssh + tmux)

Самый надёжный путь: тот же вход, что делает пульт, только руками.

```bash
ssh <пользователь>@<сервер>
tmux new -s login               # чтобы вход не оборвался, если связь пропадёт
claude auth login               # подписка Claude; ключ Console — claude auth login --console
```

Claude Code напечатает ссылку. Откройте её на своём компьютере или телефоне, войдите, скопируйте код и вставьте
его в окно tmux, Enter. Проверка:

```bash
claude auth status --text       # «Logged in …»
exit                            # закрыть окно tmux
```

Если окно входа пульта осталось открытым — посмотреть его можно так: `tmux attach -t main-setup`.

## 2. Токен с другой машины: `claude setup-token`

Если на сервере вход не проходит, а на вашем компьютере Claude Code есть и вход выполнен:

```bash
claude setup-token              # на своём компьютере: напечатает долгоживущий токен (нужна подписка Claude)
```

Токен — секрет: не пересылайте его в чатах и не кладите в git. На сервере сохраните его в окружение службы пульта —
тогда его получат все сессии, которые пульт откроет:

```bash
mkdir -p ~/.config/systemd/user/gas-pult.service.d
printf '[Service]\nEnvironment=CLAUDE_CODE_OAUTH_TOKEN=%s\n' '<токен>' \
  > ~/.config/systemd/user/gas-pult.service.d/claude.conf
chmod 600 ~/.config/systemd/user/gas-pult.service.d/claude.conf
systemctl --user daemon-reload && systemctl --user restart gas-pult
```

Для панели (`gas-pult-webapp` или как называется ваша служба) — так же. На macOS (launchd) переменную добавляют
в `EnvironmentVariables` файла `~/Library/LaunchAgents/com.github.gvriil.gas-pult.plist`.

Окна tmux наследуют окружение сервера tmux. Если tmux уже был запущен до изменения, новые сессии токен не увидят —
перезапустите сервер tmux (закроет все окна!) или выполните `tmux set-environment -g CLAUDE_CODE_OAUTH_TOKEN <токен>`.

## 3. Ключ API Anthropic (оплата по использованию)

Ключ из [console.anthropic.com](https://console.anthropic.com/settings/keys) — тем же способом, что токен в
варианте 2, только переменная `ANTHROPIC_API_KEY`. Или войти в Console прямо в окне: `claude auth login --console`.

## 4. Сторонний поставщик моделей (OpenRouter, GLM, DeepSeek)

Сессия может работать не на Anthropic, а у поставщика с Anthropic-совместимым API (`src/gas_pult/models.py`).
Claude Code при этом всё равно нужен (вариант 0), а вход в аккаунт Claude — нет:

1. Панель → «Интеграции» → «Модели» → поставщик → ключ (OpenRouter — вход в одно касание).
2. «Новая сессия» → папка → поставщик.

Ключ хранится в `~/.config/gas-pult/secrets.json` (0600), сессия запускается с `claude --settings …/profiles/<id>.json`.
Коннекторы claude.ai в таких сессиях не работают.

**Регион.** Поставщик допускается только для стран из его списка поддерживаемых. Сервер пульта и его выход в интернет — в поддерживаемой стране. Российские каналы (MAX, VK) — только с поставщиком, разрешённым для России, не Claude: Россия не входит в список стран Anthropic. У каждого человека — свой аккаунт или ключ; одна подписка Claude не делится и не перепродаётся. Подробно — `docs/COMPLIANCE.md`.

## Если ничего не помогает

- `gas-pult doctor` — что именно не так.
- Логи бота: `journalctl --user -u gas-pult -n 100`.
- Экран окна входа: `tmux capture-pane -p -t main-setup:claude-login`.
- Вопрос в [issues](https://github.com/gvriil/gas-pult/issues) — с выводом `gas-pult doctor` (без токенов и почты).
