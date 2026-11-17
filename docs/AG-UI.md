# AG-UI — нужен ли пульту (исследование, #258)

Решение владельца 17.11: AG-UI — только исследование, без кода.

## Что это

AG-UI — открытый протокол «агент ↔ интерфейс» на событиях. Источник: https://docs.ag-ui.com/introduction,
репозиторий https://github.com/ag-ui-protocol/ag-ui (лицензия MIT — `gh api repos/ag-ui-protocol/ag-ui`, 17.11.2026).
Появился из партнёрства CopilotKit с LangChain и CrewAI. Транспорт — поверх HTTP и WebSocket.

События (https://docs.ag-ui.com/concepts/events):

| Группа | События |
|---|---|
| Жизненный цикл | `RunStarted`, `RunFinished`, `RunError`, `StepStarted`, `StepFinished` |
| Текст | `TextMessageStart`, `TextMessageContent`, `TextMessageEnd`, `TextMessageChunk` |
| Инструменты | `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`, `ToolCallResult`, `ToolCallChunk` |
| Состояние | `StateSnapshot`, `StateDelta`, `MessagesSnapshot` |
| Прочее | рассуждения (`Reasoning*`), субагенты (`Subagent*`), `Raw`, `Custom` |

Подтверждение человеком отдельным событием не описано: пауза — `RunFinished` с `outcome: {type: "interrupt"}`,
продолжение — массив `resume` в следующем запуске.

Поддержка: Claude Agent SDK и Claude Managed Agents SDK — адаптеры сообщества (не Anthropic).

## Как это ложится на пульт

Пульт работает с Claude Code CLI в tmux: читает экран (`/api/screen`, `humanize.parse`) и журналы сессий
(`/api/history`, `/api/activity`). Событий от среды агента у него нет. Соответствие получилось бы таким:

| Пульт | AG-UI |
|---|---|
| новое сообщение в журнале | `TextMessageStart` / `TextMessageContent` / `TextMessageEnd` (целиком, без потока по словам) |
| инструмент в журнале (Bash, Edit…) | `ToolCallStart` / `ToolCallArgs` / `ToolCallEnd`, результат — `ToolCallResult` |
| диалог разрешения (карточка «Да / Нет») | `RunFinished` с `outcome: interrupt`; ответ — `resume` → наш `/api/select` |
| статус «работает / ждёт» | `RunStarted` / `RunFinished` |

## Вывод

Сейчас не встраивать. Пульт — свой интерфейс к своим окнам. AG-UI нужен, когда **чужой** интерфейс (сайт клиента,
CopilotKit) хочет показывать агентов пульта. Тогда дешёвый шаг — адрес только для чтения
`GET /api/agui/stream?w=<окно>` (SSE), который переводит журнал, статус и диалог в события выше; ответы — через
существующие `/api/send` и `/api/select`. Оценка — один модуль на стандартной библиотеке; делать по запросу клиента.

Не проверено: работа адаптера Claude Agent SDK; как CopilotKit ведёт себя с событиями без потока по словам.
