# Поставщики моделей: что работает и что нет

Сессия пульта — всегда Claude Code; меняется только модель, которая отвечает (`models.py`). Ниже — что из возможностей
Claude Code доступно у каждого поставщика. Сверено 04.11.2026; панель показывает то же самое («Новая сессия» → выбор
поставщика, экран поставщика, строка над полем ввода сессии, «Настройки» → «Поставщики»). Решение про интеграции —
[ADR-0002](adr/0002-integrations-provider-independent.md).

| | Claude (подписка) | OpenRouter | GLM (Z.ai) | DeepSeek | GigaChat, YandexGPT (шлюз) |
|---|---|---|---|---|---|
| `CLAUDE.md`, файлы, команды | да | да | да | да | зависит от модели шлюза |
| Интеграции через сервер (MCP) | да | да | да | да | да |
| WebFetch | да | да | да | да | да |
| WebSearch | да | не проверено | **нет** (пусто) | да, свой | нет |
| Картинки | да | да (модели Claude) | **нет** | Flash — да, V4 Pro — нет | зависит от модели |
| Коннекторы claude.ai | да | **нет** | **нет** | **нет** | **нет** |
| PushNotification, RemoteTrigger, DesignSync | да | нет | нет | нет | нет |

Почему:

- **Коннекторы claude.ai** приходят из аккаунта claude.ai. С ключом другого поставщика Claude Code их выключает:
  «claude.ai connectors are disabled because ANTHROPIC_API_KEY or another auth source is set». Замена — интеграции
  «Для любой модели» в панели: MCP-серверы в папке Claude Code (Notion, Linear, Jira и Confluence, GitHub, Google
  Диск, веб-поиск Tavily). Вход по OAuth в такой сервер действует для сессий любого поставщика.
- **WebSearch** — серверный инструмент Anthropic. Z.ai его не выполняет (результат пустой). DeepSeek поддерживает его
  сам: «The DeepSeek API natively supports the Web Search feature in Claude Code», поиск оплачивается отдельно
  ([api-docs.deepseek.com/quick_start/agent_integrations/claude_code](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code)).
  Замена — интеграция «Веб-поиск Tavily».
- **Картинки.** GLM-5.3 — «text-only inputs» ([docs.z.ai/guides/llm/glm-5.3](https://docs.z.ai/guides/llm/glm-5.3)).
  DeepSeek: `deepseek-flash` принимает картинки, `deepseek-v4-pro` заменяет их на «[Unsupported Image]»
  ([api-docs.deepseek.com/guides/anthropic_api](https://api-docs.deepseek.com/guides/anthropic_api)).
- **Модель неизвестна Claude Code** (`[claude-code:unrecognized_model]`): для такой модели Claude Code сам не знает
  окно контекста. С суффиксом `[1m]` он считает окно 1M, без суффикса — 200K; `CLAUDE_CODE_AUTO_COMPACT_WINDOW` задаёт,
  когда сжимать, и не превышает окно модели
  ([code.claude.com/docs/en/model-config](https://code.claude.com/docs/en/model-config#correct-the-window-for-a-gateway-or-custom-model-id)).

## Окно контекста и сжатие

| Поставщик | Окно по документации | Ответ до | Сжимаем на (`CLAUDE_CODE_AUTO_COMPACT_WINDOW`) |
|---|---|---|---|
| GLM-5.3 (Z.ai) | 1M — «a 1M-token context window and a maximum output length of 128K tokens» ([docs.z.ai](https://docs.z.ai/guides/llm/glm-5.3)) | 128K | **786 432** (было 1 000 000) |
| DeepSeek V4 Pro и Flash | 1M ([api-docs.deepseek.com/quick_start/pricing](https://api-docs.deepseek.com/quick_start/pricing)) | 384K | 786 432 — как советует DeepSeek ([claude_code](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code)) |

Z.ai в своей инструкции для Claude Code ставит 1 000 000 ([docs.z.ai/devpack/tool/claude](https://docs.z.ai/devpack/tool/claude)) —
это всё окно без запаса на ответ (до 128K) и без запаса на неточный подсчёт токенов чужой модели; окно GLM-5.3-Flash
в документации не указано. Поэтому берём консервативное значение — то же, что DeepSeek советует для своего окна 1M
(75 % от 2²⁰): длинная сессия сжимается раньше, но не упирается в предел поставщика. Быстрая модель DeepSeek
(`deepseek-flash` без `[1m]`) — для Claude Code окно 200K: субагенты сжимаются раньше, это безопасно.

## Автотест поставщиков

Раз в сутки (бот, `selftest.py`) и по кнопке «Проверить сейчас» («Настройки» → «Поставщики»; в боте — `/selftest`)
пульт запускает на каждом поставщике с ключом один короткий `claude -p` во временной папке:

- `CLAUDE.md` с кодовым словом — модель должна его назвать (**правила проекта**);
- событие `init` — Claude Code отдал модели **список инструментов**;
- `probe.txt` со случайной строкой — модель вызывает Read и возвращает её (**вызов инструмента**: строку не угадать);
- WebFetch страницы `https://example.com/` — инструмент без ошибки, в ответе заголовок (**чтение страницы**).

Затраты: `--max-turns 6`, `--max-budget-usd 0.50` (потолок, обычно — доли цента), без MCP-серверов
(`--strict-mcp-config`), без хуков и настроек пользователя (`--setting-sources project,local`), без журнала
(`--no-session-persistence`). Ключ — в файле настроек профиля (0600), не в аргументах. Итог — `<data>/selftest.json`;
если что-то не прошло, бот пишет владельцам одну сводку. «Claude» (подписка) не проверяется.

## Пилот: GLM + Notion + поиск (для владельца, после слияния)

1. Панель → «Интеграции» → «Для любой модели» → **Notion** → «Подключить» → «Войти в Notion» → откроется страница
   входа Notion; войдите, разрешите доступ → адрес страницы после входа (`http://localhost…/callback?code=…`, страница
   не откроется — это нормально) вставьте в панель. В «Подключено» — `notion` ✔.
2. «Интеграции» → **Веб-поиск Tavily** → «Открыть страницу, где взять ключ» (app.tavily.com → API Keys) → вставьте
   ключ → «Подключить». В «Подключено» — `tavily` ✔.
3. «Новая сессия» → папка → **GLM (Z.ai)**. Над полем ввода — «GLM: недоступно — коннекторы сайта Claude, …».
4. В сессии: «Какие у тебя MCP-инструменты? Перечисли имена». Ждём `mcp__notion__…` и `mcp__tavily__…`.
5. «Найди в Notion страницу со словом <слово> и перескажи первый абзац» — на «Экране» виден вызов
   `notion - … (MCP)`, ответ — из вашей страницы.
6. «Найди в интернете последнюю версию Claude Code и дай ссылку» — вызов `tavily - tavily_search (MCP)`, ссылка.
7. «Настройки» → «Поставщики» → «Проверить сейчас» — у GLM четыре зелёные отметки.
8. Откат: «Интеграции» → `notion`/`tavily` → «Убрать».

Если на шаге 1 «вход не подтвердился» — в сессии `/mcp` → notion → Authenticate и повторить; сессии, открытые до
подключения, видят сервер после перезапуска.
