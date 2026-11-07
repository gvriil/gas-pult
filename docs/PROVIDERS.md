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
  Диск через rclone или официальный сервер Google, «Веб-поиск» пульта). Вход по OAuth в такой сервер действует для сессий любого поставщика.
- **WebSearch** — серверный инструмент Anthropic. Z.ai его не выполняет (результат пустой). DeepSeek поддерживает его
  сам: «The DeepSeek API natively supports the Web Search feature in Claude Code», поиск оплачивается отдельно
  ([api-docs.deepseek.com/quick_start/agent_integrations/claude_code](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code)).
  Замена — интеграция «Веб-поиск» (свой сервер пульта, см. ниже).
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
2. «Интеграции» → **Веб-поиск** → сервис (Яндекс, Brave, Tavily, Exa) → «Открыть страницу, где взять ключ» → вставьте
   ключ (для Яндекса — и ID каталога) → «Подключить». В «Подключено» — `websearch` ✔.
3. «Новая сессия» → папка → **GLM (Z.ai)**. Над полем ввода — «GLM: недоступно — коннекторы сайта Claude, …».
4. В сессии: «Какие у тебя MCP-инструменты? Перечисли имена». Ждём `mcp__notion__…` и `mcp__websearch__web_search`.
5. «Найди в Notion страницу со словом <слово> и перескажи первый абзац» — на «Экране» виден вызов
   `notion - … (MCP)`, ответ — из вашей страницы.
6. «Найди в интернете последнюю версию Claude Code и дай ссылку» — вызов `websearch - web_search (MCP)`, ссылка.
7. «Настройки» → «Поставщики» → «Проверить сейчас» — у GLM четыре зелёные отметки.
8. Откат: «Интеграции» → `notion`/`websearch` → «Убрать» (ключ удаляется вместе с сервером).

Если на шаге 1 «вход не подтвердился» — в сессии `/mcp` → notion → Authenticate и повторить; сессии, открытые до
подключения, видят сервер после перезапуска.

## Базовые интеграции пульта: поиск и Google Диск (задача 48)

Два своих MCP-сервера пульта — `src/gas_pult/base_mcp.py`, один файл, только стандартная библиотека Python, stdio.
Не зависят ни от модели, ни от коннекторов claude.ai: Claude Code сам запускает их и отдаёт инструменты любой модели.

- **«Веб-поиск»** (`web_search`) — сервис по выбору: Яндекс, Brave, Tavily, Exa. Ключ — в файле 0600
  (владелец — `~/.config/gas-pult/integrations/`, человек пульта — `people/<id>/integrations/`), в `.claude.json` —
  только путь к файлу. Ключ не попадает ни в ответы инструмента, ни в журнал (ошибки сервиса — с `***`).
- **«Google Диск (rclone)»** (`drive_list`, `drive_download`, `drive_upload`) — rclone на сервере со своим
  `rclone.conf` у каждого (у пространства — в его `config/mcp/`). Скачать и загрузить — только в папке сессии:
  относительные пути, без `..`, ссылки наружу не пропускаются. Проект Google Cloud не нужен: вход —
  `rclone authorize "drive"` на компьютере с браузером, ответ — в панель.
- Пространства: `sudo bin/pult-tenant mcp <slug> websearch|drive` (`docs/TENANTS.md`, шаг 4а).

### Какой поиск выбрать (цены и условия на 07.11.2026)

| | Яндекс (Yandex Search API) | Brave Search API | Tavily | Exa |
|---|---|---|---|---|
| 1000 запросов | 488 ₽ с НДС днём, 366 ₽ ночью (00–08 МСК); отложенный — 30,5 ₽ | $5 | ≈ $8 (basic = 1 кредит по $0,008) | $7 (`auto`, до 10 результатов) |
| Бесплатно | нет; грант Yandex Cloud новым клиентам на 60 дней | $5 в месяц (≈ 1000 запросов), **нужна карта** | 1000 кредитов в месяц, без карты | $10 в месяц, без карты |
| Индекс, русский | свой индекс Яндекса — лучший для рунета (`SEARCH_TYPE_RU`, регион 225) | свой индекс, `country`/`search_lang` | чужой, `country: "russia"` | свой нейроиндекс, `userLocation: "RU"` |
| Из России | работает: рубли, карта «Мир» | Россия — в списке недоступных стран Brave; оплата только в USD | Россия прямо названа в условиях (санкции) | запрет стран под эмбарго США; российские карты не проходят |
| Из NL (сервер пульта) | нерезидент — только USD, картой не российского банка, счёт одобряют вручную | без ограничений | без ограничений | без ограничений |
| Официальный MCP | удалённый, IAM-токен на 12 ч | `npx` (Node 22+) | удалённый или `npx` | удалённый или `npx` |

Источники: [aistudio.yandex.ru/docs/ru/search-api/pricing](https://aistudio.yandex.ru/docs/ru/search-api/pricing),
[API v2 web search](https://aistudio.yandex.ru/docs/en/search-api/api-ref/WebSearch/search),
[docs.yandex.cloud — нерезиденты](https://docs.yandex.cloud/int/en/billing/qa/non-resident.md),
[brave.com/search/api](https://brave.com/search/api/),
[Brave — Unavailable Jurisdictions](https://support.brave.app/hc/id/articles/34271483229581-Unavailable-Jurisdictions-for-Brave-Services),
[tavily.com/pricing](https://www.tavily.com/pricing), [tavily.com/terms](https://www.tavily.com/terms) (§17.1, §15.3f),
[exa.ai/pricing](https://exa.ai/pricing), [условия Exa](https://exa.ai/assets/Exa_Labs_Terms_of_Service.pdf) (§10.7).
Доступность из России — по документации и условиям сервисов, **напрямую не проверено**.

**Рекомендация.** Для клиентов из России и русских запросов — **Яндекс** (по умолчанию в панели): свой индекс рунета,
договор и оплата в рублях; ключ — API-ключ сервисного аккаунта с ролью `search-api.webSearch.user` и ID каталога.
Для сервера в NL и запросов по миру — **Brave** (дешевле всех, $5 за 1000) или **Tavily**, если нужна бесплатная
квота без карты. Официальные MCP-серверы не берём: у Яндекса токен живёт 12 часов, остальным нужен Node.js — свой
сервер на stdlib проще и одинаков для всех сервисов.

Качество выдачи на русском (5–10 одинаковых запросов) **не сравнивалось: ключей поиска на сервере пока нет**. Как
появятся — подключить по очереди в «Интеграциях» и задать в сессии одни и те же запросы.

### Одна задача на трёх моделях

`python -m gas_pult.selftest base [claude zai deepseek]` — на каждом поставщике один `claude -p` с задачей: «найди в
интернете „курс рубля сегодня“ и сохрани сводку с адресом первого результата в summary.md; покажи три последних файла
на Диске и скачай самый новый». Серверы — свои (`--mcp-config`, `--strict-mcp-config`), сервис поиска — локальная
подмена в формате Brave со случайным адресом (его не угадать), Диск — настоящий rclone с удалённым диском `alias` на
временную папку. Проверяется то, что сделано на деле: вызовы инструментов, адрес в `summary.md`, содержимое
скачанного файла. Ключи сервисов не нужны; Google и качество поиска этой проверкой не покрываются.

Прогон 07.11.2026 (сервер в NL):

| Поставщик | web_search | сводка в файле | drive_list | drive_download | Время | Расход |
|---|---|---|---|---|---|---|
| Claude (подписка) | да | да | да | да | 13 с | $0,087 (по подписке) |
| GLM (Z.ai) | да | да | да | да | 67 с | $0,094 |
| DeepSeek | да | да | да | да | 14 с | $0,145 |

Все три модели вызвали одни и те же инструменты в одном порядке (`web_search` → `drive_list` → `Write` →
`drive_download`) и дали одинаковый результат.
