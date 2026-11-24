# Договор-оферта на услуги пульта GASTECH — черновик

> # ЧЕРНОВИК, ДО ПРОВЕРКИ ЮРИСТОМ. НЕ ПУБЛИКОВАТЬ ДО «ДА» ВЛАДЕЛЬЦА.
>
> Это не действующая оферта и не юридическая консультация. Цены, сроки и реквизиты — заглушки в `[квадратных
> скобках]`. Публичной страницы и маршрута в панели у этого текста нет и не будет до решения владельца.
> Черновик от 17.11.2026. English version — [below](#offer-agreement-for-gastech-pult-services--draft).

**Как читать.** Этот документ — договор с **клиентом** (человеком или компанией), который платит за пульт и услуги.
Правила для **людей**, которые работают в пульте, — в пользовательском соглашении: [`TERMS.md`](TERMS.md) и его
понятное изложение на странице `/terms`. Оферта на него ссылается и не повторяет его.

Слова «уточнить» и «решает владелец» — открытые вопросы. Их закрывают владелец и юрист до публикации.

---

## 1. Термины

- **Исполнитель** — `[реквизиты: ИП, ФИО, ОГРНИП, ИНН — заглушка]`. Для клиентов вне России — см. раздел 13.
- **Клиент** — человек или организация, принявшие оферту.
- **Пульт** — программа gas-pult: Telegram-бот и веб-панель, через которые люди клиента ведут сессии ИИ-агентов
  (Claude Code и совместимых).
- **Сервер** — компьютер, на котором работают пульт и агенты. Он бывает двух видов:
  - **сервер клиента** — его арендует и администрирует клиент;
  - **пространство у исполнителя** — изолированная часть сервера исполнителя со своим лимитом диска, памяти и
    процессора ([`TENANTS.md`](TENANTS.md)). Сейчас пространства есть только для демо и пилота — **уточнить**,
    продаём ли их как постоянное размещение.
- **Поставщик модели** — Anthropic, OpenRouter, Z.ai, DeepSeek и другие. Он даёт модель по своим условиям.
- **Токены** — единицы, которыми поставщик модели считает объём работы модели и выставляет счёт.

## 2. Предмет

2.1. Исполнитель даёт клиенту право пользоваться пультом и оказывает услуги из раздела 3. Клиент платит по
разделу 4.

2.2. Оферта принимается оплатой счёта или нажатием «Подключить» в мастере подключения — **уточнить** способ
акцепта с юристом (ст. 438 ГК РФ). Договор действует с даты акцепта.

2.3. Лицензия кода пульта — PolyForm Noncommercial 1.0.0 ([`LICENSE`](../LICENSE)). Она не разрешает коммерческое
использование. Коммерческое использование клиентом разрешает **этот договор** и только на его срок.

## 3. Состав услуг

### 3.1. Что входит

| Услуга | Что это значит | Где описано |
|---|---|---|
| Установка пульта | На сервер клиента или в пространство у исполнителя: бот, панель, служба, проверка `gas-pult doctor` | [`ONBOARDING-BUSINESS.md`](ONBOARDING-BUSINESS.md) |
| Пульт на срок подписки | Бот и панель; роли «владелец», «участник», «наблюдатель»; вопросы агента — кнопками; голос | [`PRODUCT.md`](PRODUCT.md), [`AUTH.md`](AUTH.md) |
| Обновления | Новые версии пульта в течение срока подписки | [`CHANGELOG.md`](../CHANGELOG.md) |
| Модули-агенты | Готовые агенты под отрасли из каталога — по тарифу | [`MODULES.md`](MODULES.md) |
| Учёт расхода | В пространстве у исполнителя — расход по журналам Claude Code, норма в день и запас на период | `space_budget.py` |
| Поддержка | Каналы и сроки — раздел 8 | — |

### 3.2. Чего НЕ предоставляем

- **Доступ к моделям не продаём и не перепродаём.** Модель даёт поставщик по своим условиям. Исключение — раздел 5.3.
- **Подписку Claude (Pro, Max) не делим.** Личная подписка одного человека не передаётся клиенту и его людям.
  Подписка исполнителя в пространство клиента не копируется никогда ([`TENANTS.md`](TENANTS.md)).
- **Обход ограничений стран не делаем.** Модель работает только в странах, которые поддерживает её поставщик.
  VPN, прокси и чужие аккаунты для этого не используем ([`COMPLIANCE.md`](COMPLIANCE.md)). Claude для людей из
  России закрыт.
- **Результат работы модели не гарантируем.** Ответы модели могут быть неверны. Важные действия (оплата, отправка
  людям, удаление) агент делает только после «Да» человека — проверяйте перед нажатием.
- **Изоляцию агента не обеспечиваем.** Главная защита — режим разрешений Claude Code. Пульт не шифрует историю на
  диске ([`SECURITY.md`](../SECURITY.md)).
- **Администрирование сервера клиента не входит.** Обновления системы, бэкапы, домен, сертификат — обязанность
  клиента, если не заказана отдельная услуга (раздел 7).
- **Бэкап данных на сервере клиента не входит.** Команды бэкапа для сервера клиента в пульте нет. Для пространств у
  исполнителя есть `pult-tenant backup` — **уточнить**, как часто и сколько хранить.
- **Восстановление окон агентов после перезагрузки сервера** — пульт сам его не делает
  ([`ONBOARDING-BUSINESS.md`](ONBOARDING-BUSINESS.md), раздел 5) — **уточнить**, не изменилось ли.
- **Защиту аккаунта Telegram** обеспечивает сам человек: облачный пароль Telegram.
- **Юридические, бухгалтерские и медицинские советы** агенты не дают как профессиональные услуги.

## 4. Тарифы и оплата

4.1. Цены — в рублях за месяц. Сетка утверждена владельцем 24.11.2026.

| Тариф | Что это | Срок | Цена |
|---|---|---|---|
| **Демо** | Панель на выдуманных данных, без входа (`/?demo`); страница предложения `/offer/<код>` | без срока | бесплатно |
| **Пробный период** | Пульт на сервере клиента или в пространстве у исполнителя; модель — по ключу клиента или с нормой расхода | `[N дней — решает владелец]` | `[цена — решает владелец]` |
| **Пилот** | Установка, 1–3 модуля, настройка под задачи клиента, неделя сопровождения, замер «до/после» | 4 недели ([`PRODUCT.md`](PRODUCT.md)) | `[цена — решает владелец]` |
| **Подписка** | Пульт, обновления, поддержка по разделу 8; тариф — по таблице 4.1.1 | месяц или год | по тарифу, за пространство |

4.1.1. **Тарифы подписки.** Единица — **задача**: одно поручение агенту (ответить на заявку, собрать КП, отчёт).
Задача на базовой модели — 1; сильная модель или длинная задача списывает больше (множители — в прайс-листе).

| Тариф | Цена, ₽/мес | Задач в месяц | Параллельных агентов | Память | Диск (с бэкапом) | Поддержка |
|---|---|---|---|---|---|---|
| **Старт** | 4 990 | 1 500 (≈50 в день) | 2 | 1 ГБ | 5 ГБ | Telegram, рабочие дни |
| **Бизнес** | 9 990 | 5 000 | 4 | 2 ГБ | 20 ГБ | + ответ в течение 4 рабочих часов |
| **Про** | 19 990 | 15 000 | 8 | 4 ГБ | 50 ГБ | + личный менеджер, ежемесячный разбор |
| **Выделенный** | от 39 900 | 20 000 (больше — по договору) | до 40 | своя ВМ 8 vCPU / 32 ГБ | 900 ГБ | + SLA, окно работ, свой адрес |

4.1.2. **Лимит — пауза, а не списание.** Кончились задачи периода — новые поручения агентам не принимаются до
докупки (раздел 6) или нового периода. Без согласия клиента **ничего не списывается**. На **80 %** и **100 %**
лимита — сообщение в Telegram и в пульте.

4.2. **Пробный период.** По окончании пробного периода платная подписка сама **не** начинается. Клиент
подтверждает её оплатой счёта. Не подтвердил — доступ к пульту в пространстве у исполнителя прекращается, данные
хранятся `[N дней — решает владелец]`, затем удаляются (раздел 10).

4.3. **Оплата.** Подписка — предоплата за период: `[100 % вперёд за месяц или год — решает владелец]`. Счёт —
`[способ: счёт ИП, карта — решает владелец]`. Сейчас идёт пилот: пульт платежей не принимает
(пользовательское соглашение, раздел «Оплата»).

4.4. **Продление.** `[Автопродление: да / нет — решает владелец]`. Если да — исполнитель напоминает о списании
за `[N дней]` до него.

4.5. **Изменение цен.** Новая цена действует со следующего оплаченного периода. Исполнитель сообщает о ней не
позднее чем за `[30 дней — решает владелец]`.

4.6. **Неоплата.** Не оплачен счёт — исполнитель вправе ограничить доступ к пульту через `[N дней]` после срока
оплаты. Данные не удаляются до срока из раздела 10.

## 5. Лимиты: модели и токены

### 5.1. Чей ключ модели

| Вариант | Кто платит поставщику | Кто отвечает за условия поставщика |
|---|---|---|
| **Ключ клиента** (по умолчанию) | Клиент — напрямую поставщику | Клиент: свой аккаунт, страна, допустимое использование |
| **Ключ исполнителя** (только в пространстве у исполнителя) | Исполнитель; клиент платит исполнителю по разделу 5.3 | Исполнитель — перед поставщиком; клиент — по пользовательскому соглашению |

5.2. **Ключ клиента.** Токены и превышение считает поставщик модели по своим тарифам. Исполнитель расход не
ограничивает и за него не отвечает. Пульт показывает, сколько контекста и лимита подписки осталось у сессии
([`PRODUCT.md`](PRODUCT.md)). Если сессия упёрлась в лимит подписки, пульт ставит один повтор на время сброса
лимита (`limitretry.py`). Если задана цепочка запасных поставщиков, пульт сам переключает сессию на следующего и
сообщает об этом (`fallback.py`).

5.3. **Ключ исполнителя.** Только API-ключ по коммерческим условиям поставщика — не личная подписка.
**Уточнить у юриста и по условиям каждого поставщика**, можно ли включать расход его модели в нашу цену.
Как устроен лимит (так работает код сейчас, `space_budget.py`):

- **норма в день** в долларах США: `[N USD — решает владелец]`;
- **запас периода** = норма × число дней периода (по умолчанию 30) + пополнения. В загруженный день можно потратить
  больше нормы за счёт будущих дней. Неистраченное остаётся в запасе до конца периода;
- **потолок дня** — по желанию (кратно норме), по умолчанию выключен;
- **расход** считается по журналам Claude Code. Для Claude — по ценам API; для OpenRouter — по счёту за каждый ответ;
  для Z.ai и DeepSeek — оценка по токенам и тарифу поставщика. Оценка может расходиться со счётом поставщика;
- на **80 % и 100 %** запаса владелец пульта получает сообщение;
- запас исчерпан — новые сообщения агентам в этом пространстве не принимаются до пополнения или до нового периода.
  Сверх запаса без согласия клиента **ничего не списывается**.

5.4. **Превышение.** Клиент пополняет запас кнопкой «+ неделя», «+ 2 недели» или «+ $10» (так в боте сейчас). Цена
пополнения — `[решает владелец: по расходу + наценка / пакетом]`. Неистраченное пополнение в следующий период
`[переносится / не переносится — решает владелец]`.

5.5. **Другие лимиты пространства у исполнителя** (по умолчанию, [`TENANTS.md`](TENANTS.md)): диск 2 ГБ, память
1 ГБ, процессор 80 % одного ядра, до 128 процессов. Значения для платных тарифов — `[решает владелец]`.

## 6. Докупка

| Что | Как сейчас | Цена |
|---|---|---|
| Место на диске | +10 ГБ диска с бэкапом. Образ диска пространства задаётся при создании (`pult-tenant create`) — **уточнить**, можно ли увеличить без пересоздания | 290 ₽/мес |
| Задачи сверх тарифа | +1 000 задач | 1 290 ₽ |
| Параллельный агент | +1 агент (0,5 ГБ памяти и доля ядра) | 390 ₽/мес |
| Память | +1 ГБ | 590 ₽/мес |
| Запас расхода модели | Пополнение запаса (раздел 5.4) | `[решает владелец]` |
| Модули-агенты сверх тарифа | Каталог — [`MODULES.md`](MODULES.md) | `[за модуль в месяц — решает владелец]` |
| Люди сверх тарифа | Роли «участник», «наблюдатель» | `[решает владелец]` |
| Голоса ElevenLabs | Только по ключу клиента; текст и голос уходят в ElevenLabs | платит клиент поставщику |

Докупка — по кнопке в пульте, цена видна до покупки. Действует до конца оплаченного периода. В следующий период
переносится только по подтверждению клиента — без согласия клиента ничего не списывается.

## 7. Дополнительные услуги по заявке

Не входят в подписку. Каждая — по отдельной заявке и смете.

| Услуга | Примеры | Как заказать | Цена |
|---|---|---|---|
| Аудит процессов | 2 встречи, карта 5–10 процессов, замер «сколько времени сейчас», смета. Засчитывается во внедрение, если клиент его заказывает | Заявка (раздел 8) | 15 000 ₽ фикс |
| Интеграция | Почта (IMAP/SMTP) — 5 000 ₽; Telegram (бот или чат) — 5 000 ₽; таблицы Google/Яндекс — 7 000 ₽; Битрикс24 (одна воронка) — 15 000 ₽; 1С (типовая конфигурация) — от 30 000 ₽, нестандарт — по аудиту | Заявка (раздел 8) → смета → «Да» клиента | от 5 000 ₽ |
| Свой модуль-агент | Агент под процесс клиента: данные, расписание, решения кнопками | То же | `[решает владелец]` |
| Консультация | Как поручать работу агентам, разбор процесса, обучение людей | Почасово или пакетом | `[решает владелец]` |
| Администрирование сервера | Обновления, бэкап, домен, сертификат | Ежемесячно | `[решает владелец]` |
| Перенос | С пространства у исполнителя на сервер клиента | Разово | `[решает владелец]` |

Сроки по заявке — в смете. Результат принимает клиент. Нет замечаний за `[N рабочих дней]` — результат принят.

## 8. Поддержка

8.1. **Каналы** (то, что есть сейчас):

- чат с ботом пульта клиента — для владельца пульта;
- `[контакт исполнителя: Telegram или почта — заглушка]`;
- публичные вопросы по коду — GitHub Issues проекта;
- уязвимости — только приватно: GitHub → Security → Report a vulnerability. Срок первого ответа — **7 дней**
  ([`SECURITY.md`](../SECURITY.md)).

8.2. **Сроки ответа.** **SLA нет.** Исполнитель не обещает время ответа, время исправления и долю времени работы
(uptime). Отвечаем по рабочим дням, `[часы и часовой пояс — решает владелец]`, по мере возможности.
Цель, а не обязательство, — `[N рабочих часов — решает владелец]`.

8.3. **Чего поддержка не делает:** не отвечает за поставщиков моделей и Telegram, не восстанавливает данные без
бэкапа, не администрирует сервер клиента без услуги из раздела 7.

8.4. SLA с компенсацией — **не предлагаем**, пока нет круглосуточного дежурства и замера доступности.

## 9. Данные и персональные данные

9.1. **Где данные.** На сервере клиента: сессии, журналы Claude Code, настройки, люди пульта (файлы с правами 0600).
В пространстве у исполнителя — на сервере исполнителя, в изолированной папке пространства.

9.2. **Что уходит наружу** ([`PRODUCT.md`](PRODUCT.md), раздел «Безопасность и данные»): поставщику модели — то,
что агент читает в работе; Telegram — ответы и уведомления людям с ролью; почтовому серверу клиента — коды входа,
если клиент включил почту. Ключи и пароли в сообщениях пульт заменяет заглушкой до отправки агенту — это снижает
риск, но **не гарантирует**, что секрет не попадёт к модели.

9.3. **Роли по закону.** Для данных, которые клиент кладёт в пульт, клиент — оператор, исполнитель — лицо,
обрабатывающее данные по поручению (только в пространстве у исполнителя). На сервере клиента исполнитель данные не
обрабатывает, кроме случаев доступа по заявке. **Уточнить у юриста.**

9.4. **Россия, 152-ФЗ.** Исполнитель **не** гарантирует соответствие 152-ФЗ. Что известно:

- запросы к зарубежной модели — трансграничная передача; пульт её не ограничивает и не отмечает;
- для персональных данных граждан РФ нужны сервер в России, уведомление Роскомнадзора и согласия субъектов —
  до начала работы; это делает клиент как оператор;
- российские модели (GigaChat, YandexGPT через шлюз клиента) **не проверены** с реальным шлюзом и ключами
  ([`RU-MODELS.md`](RU-MODELS.md));
- до ответа юриста персональные данные клиентов в РФ в пульт **не загружать**.

9.5. **ЕС, GDPR.** Исполнитель **не** заявляет соответствие GDPR. Договора обработки данных (DPA) и списка
субпроцессоров нет. Поставщики моделей обрабатывают данные по своим условиям. До регистрации компании в ЕС
(раздел 13) персональные данные жителей ЕС в пространство у исполнителя не загружать.

9.6. **Обучение моделей.** Исполнитель данные клиента для обучения моделей не использует. Использует ли их
поставщик модели — определяют его условия и настройки аккаунта клиента.

9.7. **Выгрузка.** На сервере клиента данные и так у клиента. Из пространства у исполнителя — архив папки
пространства по заявке в течение `[N дней — решает владелец]`.

## 10. Расторжение и возврат

10.1. **Клиент** отказывается от подписки в любой момент: сообщение в канал поддержки. Доступ сохраняется до конца
оплаченного периода.

10.2. **Исполнитель** вправе расторгнуть договор:
- с уведомлением за `[30 дней — решает владелец]` — без причины;
- сразу — при нарушении пользовательского соглашения, условий поставщика модели или закона.

10.3. **Возврат.** `[Решает владелец]`. Варианты для выбора:
- оплаченный период не возвращается, кроме случаев, когда этого требует закон;
- или возврат за неиспользованные полные месяцы;
- исполнитель расторгает договор без вины клиента — возвращает неиспользованный остаток оплаты и запаса расхода.

10.4. **Данные после расторжения.** На сервере клиента — остаются у клиента; клиент удаляет пульт сам. В пространстве
у исполнителя — архив по заявке в течение `[N дней]`, затем удаление (`pult-tenant destroy`).

10.5. Для потребителей (человек, не для бизнеса) действуют права по Закону РФ «О защите прав потребителей» —
**уточнить у юриста**, применима ли оферта к физлицам или только к ИП и юрлицам.

## 11. Ответственность

11.1. Пульт и услуги — «как есть». Исполнитель не отвечает за:
- ответы и действия моделей, в том числе подтверждённые человеком кнопкой «Да»;
- перерывы у поставщиков моделей, Telegram, хостинга и сетей;
- последствия команд, которые выполнили люди клиента;
- косвенные убытки и упущенную выгоду.

11.2. **Предел ответственности** — сумма, которую клиент заплатил исполнителю за последние `[3 / 6 / 12 месяцев —
решает владелец]`. Предел не действует при умысле и в случаях, где закон его запрещает.

11.3. Клиент отвечает за свои ключи, своих людей, их роли и за соблюдение условий поставщиков моделей.

## 12. Изменение оферты

Исполнитель меняет оферту, публикуя новую редакцию. Для действующих клиентов новая редакция действует со
следующего оплаченного периода. Клиент не согласен — отказывается по разделу 10.1.

## 13. Право и споры

13.1. **Россия.** Исполнитель — ИП в России `[реквизиты]`. Право — Российской Федерации. Сначала претензия, срок
ответа — `[30 дней — решает владелец]`. Затем — суд по месту исполнителя `[уточнить у юриста]`.

13.2. **Международные клиенты.** **Пометка: после регистрации компании в Испании.** До неё международным
клиентам оферта не предлагается. Право, суд, налоги, GDPR-документы (DPA, субпроцессоры) — после регистрации и
проверки юристом.

13.3. Остальное — по закону. Недействительный пункт не отменяет остальные.

## 14. Реквизиты

`[реквизиты — заглушка: наименование, ОГРНИП, ИНН, адрес для претензий, банк. Реальные данные в публичный
репозиторий не вносятся.]`

---

## Откуда взято

Структура разделов — по образцу сервисов ниже. Сверено 17.11.2026 по первоисточникам.

| Раздел оферты | Сервис | Что взяли | URL |
|---|---|---|---|
| 2, 13.1 Акцепт, право РФ, претензия | Яндекс 360 для бизнеса | Акцепт нажатием кнопки (ст. 438 ГК РФ, п. 6); право РФ, претензионный порядок, суд по месту исполнителя (п. 14) | https://yandex.ru/legal/oferta_business/ru/ |
| 3.2 Чего не предоставляем | Vercel | Сторонние сервисы и ИИ-поставщики — по их условиям (Non-Vercel Services) | https://vercel.com/legal/terms |
| 4.1–4.2 Пробный период | Яндекс 360; Notion | Срок и ограничения пробного периода задаёт исполнитель (п. 4.2.6); пробный Business на 30 дней | https://yandex.ru/legal/oferta_business/ru/ · https://www.notion.com/help/upgrade-or-downgrade-your-plan |
| 4.3 Предоплата | Яндекс 360 | Предоплата 100 % до начала периода (п. 5.6); при недостатке средств доступ ограничивается (п. 5.11) | https://yandex.ru/legal/oferta_business/ru/ |
| 4.4, 10.1 Продление и отказ | Notion | Автопродление до отмены; после отмены доступ — до конца оплаченного периода | https://www.notion.com/help/upgrade-or-downgrade-your-plan |
| 5.3 Норма и уведомления | Vercel | Бюджет на период, уведомления на 50/75/100 %, пауза при достижении бюджета | https://vercel.com/docs/spend-management |
| 5.4 Превышение | Vercel; Linear | Оплата сверх включённого объёма по факту; ИИ — по потреблению (Linear, п. 4.5) | https://vercel.com/legal/terms · https://linear.app/terms |
| 6 Докупка места | Яндекс 360 | «Увеличение места на Диске сотрудника, с доплатой» | https://360.yandex.ru/business/tariff/ |
| 6 Докупка функций | Notion | Добавки (кредиты для агентов, свой домен, премиум-поддержка) | https://www.notion.com/pricing |
| 8 Поддержка без SLA | Vercel; Linear; Яндекс 360 | Vercel: поддержка «может, но не обязан»; Linear: нет гарантии бесперебойной работы; Яндекс: поддержка по Регламенту, срок в оферте не указан (п. 4.1.2) | https://vercel.com/legal/terms · https://linear.app/terms · https://yandex.ru/legal/oferta_business/ru/ |
| 9.3 Роли по ПДн | Яндекс 360 | Независимые операторы для регистрационных данных; прочие данные — по поручению клиента (п. 11) | https://yandex.ru/legal/oferta_business/ru/ |
| 9.6 Обучение моделей | Vercel | На части тарифов контент используется для обучения ИИ по умолчанию — мы так не делаем и пишем это прямо | https://vercel.com/legal/terms |
| 10.3 Возврат | Linear; Vercel; Notion | Платежи невозвратные, кроме расторжения по вине исполнителя; полный возврат в первые 3/30 дней (Notion) | https://linear.app/terms · https://vercel.com/legal/terms · https://www.notion.com/help/upgrade-or-downgrade-your-plan |
| 10.4 Данные после расторжения | Linear | Удаление в течение 30 дней после расторжения (п. 5.3) | https://linear.app/terms |
| 11.2 Предел ответственности | Linear; Vercel; Яндекс 360 | 12 месяцев платежей (Linear); 6 месяцев или $100 (Vercel); 3 месяца (Яндекс, п. 12.5) | https://linear.app/terms · https://vercel.com/legal/terms · https://yandex.ru/legal/oferta_business/ru/ |

**Не проверено** (страница не открылась при сверке 17.11.2026):
- Notion Master Subscription Agreement — https://app.notion.com/notion/terms (404 у загрузчика; страница рисуется
  скриптом). Использованы только страницы помощи и цен Notion выше.
- OpenAI Services Agreement — https://openai.com/policies/services-agreement/ и
  https://openai.com/policies/service-terms/ (403). Выводов по OpenAI в черновике нет.

---
---

# Offer Agreement for GASTECH Pult Services — DRAFT

> # DRAFT, NOT REVIEWED BY A LAWYER. DO NOT PUBLISH WITHOUT THE OWNER'S "YES".
>
> This is not a binding offer and not legal advice. Prices, terms and company details are placeholders in
> `[square brackets]`. This text has no public page and no panel route until the owner decides.
> Draft of 17 November 2026. If the Russian and English texts differ, the Russian text applies (to be confirmed
> by the lawyer).

**How to read.** This document is the contract with the **Customer** (a person or company) who pays for the Pult and
services. Rules for the **people** who work in the Pult are in the user agreement: [`TERMS.md`](TERMS.md) and its
plain-language page `/terms`. This offer refers to it and does not repeat it.

"To confirm" and "owner decides" mark open questions for the owner and the lawyer.

## 1. Definitions

- **Provider** — `[company details: sole proprietor, name, registration numbers — placeholder]`. For customers
  outside Russia, see section 13.
- **Customer** — a person or organization that accepted the offer.
- **Pult** — the gas-pult software: a Telegram bot and a web panel to run AI agent sessions (Claude Code and
  compatible).
- **Server** — the computer that runs the Pult and the agents:
  - **Customer server** — rented and administered by the Customer;
  - **Space at the Provider** — an isolated part of the Provider's server with its own disk, memory and CPU limits
    ([`TENANTS.md`](TENANTS.md)). Today spaces exist only for demos and pilots — **to confirm** whether we sell them
    as permanent hosting.
- **Model provider** — Anthropic, OpenRouter, Z.ai, DeepSeek and others, under their own terms.
- **Tokens** — the units a model provider uses to measure and bill model work.

## 2. Subject

2.1. The Provider grants the Customer the right to use the Pult and provides the services in section 3. The
Customer pays under section 4.

2.2. The offer is accepted by paying an invoice or by pressing "Connect" in the onboarding wizard — **to confirm**
with the lawyer. The agreement starts on acceptance.

2.3. The Pult code licence is PolyForm Noncommercial 1.0.0 ([`LICENSE`](../LICENSE)). It does not allow commercial
use. **This agreement** allows the Customer's commercial use, for its term only.

## 3. Services

### 3.1. Included

| Service | Meaning | Reference |
|---|---|---|
| Installation | On the Customer server or in a Space at the Provider: bot, panel, service, `gas-pult doctor` check | [`ONBOARDING-BUSINESS.md`](ONBOARDING-BUSINESS.md) |
| The Pult for the subscription term | Bot and panel; owner, member and viewer roles; agent questions as buttons; voice | [`PRODUCT.md`](PRODUCT.md), [`AUTH.md`](AUTH.md) |
| Updates | New Pult versions during the subscription | [`CHANGELOG.md`](../CHANGELOG.md) |
| Agent modules | Ready industry agents from the catalogue, per plan | [`MODULES.md`](MODULES.md) |
| Usage tracking | In a Space at the Provider: spend from Claude Code logs, a daily rate and a period reserve | `space_budget.py` |
| Support | Channels and response times — section 8 | — |

### 3.2. NOT included

- **We do not sell or resell model access.** The model provider supplies the model under its terms. Exception —
  section 5.3.
- **We do not share a Claude subscription (Pro, Max).** One person's personal subscription is never given to the
  Customer or its people. The Provider's subscription is never copied into a Customer space.
- **We do not bypass country restrictions.** A model works only in countries its provider supports. No VPNs,
  proxies or other people's accounts ([`COMPLIANCE.md`](COMPLIANCE.md)).
- **We do not guarantee model output.** Answers can be wrong. Important actions (payments, sending to people,
  deletion) run only after a person's "Yes" — check before you press it.
- **We do not sandbox the agent.** The main protection is Claude Code's permission mode. The Pult does not encrypt
  history on disk ([`SECURITY.md`](../SECURITY.md)).
- **We do not administer the Customer server** (OS updates, backups, domain, certificate) unless ordered (section 7).
- **No backups on the Customer server.** The Pult has no backup command for it. Spaces at the Provider have
  `pult-tenant backup` — **to confirm** frequency and retention.
- **No restore of agent windows after a server reboot** — **to confirm** whether this changed.
- **Telegram account security** is the person's own job: enable the Telegram cloud password.
- **No professional legal, accounting or medical advice** from agents.

## 4. Plans and payment

4.1. Prices are in the price list or the invoice. This offer contains no prices.

| Plan | What it is | Term | Price |
|---|---|---|---|
| **Demo** | Panel on made-up data, no login (`/?demo`); offer page `/offer/<code>` | no limit | free |
| **Trial** | The Pult on the Customer server or in a Space; model on the Customer's key or with a spend rate | `[N days — owner decides]` | `[price — owner decides]` |
| **Pilot** | Installation, 1–3 modules, setup for the Customer's tasks, one week of support, before/after measurement | 4 weeks | `[price — owner decides]` |
| **Subscription** | The Pult, updates, support per section 8 | month or year | `[price — owner decides]` per `[server / space / person — owner decides]` |

4.2. **Trial.** A paid subscription does **not** start automatically after the trial. The Customer confirms it by
paying. No confirmation — access in a Space ends; data is kept `[N days]`, then deleted (section 10).

4.3. **Payment.** Prepayment per period: `[100 % in advance — owner decides]`. Method: `[owner decides]`. The Pult is
in a pilot and takes no payments today.

4.4. **Renewal.** `[Auto-renewal: yes / no — owner decides]`. If yes, the Provider reminds the Customer `[N days]`
before the charge.

4.5. **Price changes** apply from the next paid period, with at least `[30 days — owner decides]` notice.

4.6. **Non-payment.** The Provider may restrict access `[N days]` after the due date. Data is not deleted before the
term in section 10.

## 5. Limits: models and tokens

### 5.1. Whose model key

| Option | Who pays the model provider | Who is responsible for the provider's terms |
|---|---|---|
| **Customer key** (default) | The Customer, directly | The Customer: own account, country, acceptable use |
| **Provider key** (Spaces at the Provider only) | The Provider; the Customer pays the Provider per 5.3 | The Provider towards the model provider; the Customer per the user agreement |

5.2. **Customer key.** The model provider counts tokens and overage under its own prices. The Provider does not
limit or answer for that spend. The Pult shows each session's remaining context and subscription limit. When a
session hits a subscription limit, the Pult schedules one retry at the reset time (`limitretry.py`). With a fallback
chain set, the Pult switches the session to the next provider and says so (`fallback.py`).

5.3. **Provider key.** Only an API key under the provider's commercial terms — never a personal subscription.
**To confirm with the lawyer and each provider's terms** whether model spend may be included in our price.
How the limit works (current code, `space_budget.py`):

- **daily rate** in USD: `[N USD — owner decides]`;
- **period reserve** = daily rate × days in the period (30 by default) + top-ups. A busy day may use more than the
  rate from future days. Unused reserve stays until the period ends;
- **daily cap** — optional (a multiple of the rate), off by default;
- **spend** comes from Claude Code logs: Claude at API prices; OpenRouter from per-answer billing; Z.ai and DeepSeek —
  an estimate from tokens and the provider's price. Estimates may differ from the provider's invoice;
- the Pult owner gets a message at **80 % and 100 %** of the reserve;
- reserve used up — the space accepts no new agent messages until a top-up or a new period. **Nothing is charged
  above the reserve** without the Customer's consent.

5.4. **Overage.** The Customer tops up with "+ week", "+ 2 weeks" or "+ $10" (as in the bot today). Top-up price —
`[owner decides: at cost + margin / packages]`. Unused top-ups `[carry over / expire — owner decides]`.

5.5. **Other Space limits** (defaults, [`TENANTS.md`](TENANTS.md)): 2 GB disk, 1 GB memory, 80 % of one CPU core, up
to 128 processes. Paid-plan values — `[owner decides]`.

## 6. Add-ons

| What | Today | Price |
|---|---|---|
| Space disk | Set at creation (`pult-tenant create`) — **to confirm** whether it can grow without re-creation | `[per N GB per month — owner decides]` |
| Model spend reserve | Top-up (5.4) | `[owner decides]` |
| Extra agent modules | Catalogue — [`MODULES.md`](MODULES.md) | `[per module per month — owner decides]` |
| Extra people | Member and viewer roles | `[owner decides]` |
| ElevenLabs voices | Customer key only; text and audio go to ElevenLabs | paid by the Customer to the vendor |

Add-ons last until the end of the paid period and renew with the subscription unless cancelled.

## 7. Additional services on request

Not in the subscription. Each one needs a request and an estimate.

| Service | Examples | How to order | Price |
|---|---|---|---|
| Integration | Connect a service via MCP or API: 1C, MoySklad, Bitrix24, mail, tracker | Request (section 8) → estimate → Customer's "Yes" | `[owner decides]` |
| Custom agent module | An agent for the Customer's process: data, schedule, button decisions | Same | `[owner decides]` |
| Consulting | How to delegate to agents, process review, team training | Hourly or package | `[owner decides]` |
| Server administration | Updates, backups, domain, certificate | Monthly | `[owner decides]` |
| Migration | From a Space at the Provider to the Customer server | One-off | `[owner decides]` |

Deadlines are in the estimate. No remarks within `[N business days]` — the result is accepted.

## 8. Support

8.1. **Channels** (what exists today):
- the Pult bot chat — for the Pult owner;
- `[Provider contact: Telegram or email — placeholder]`;
- public code questions — the project's GitHub Issues;
- vulnerabilities — privately only: GitHub → Security → Report a vulnerability. First response within **7 days**
  ([`SECURITY.md`](../SECURITY.md)).

8.2. **Response times.** **There is no SLA.** The Provider does not promise response time, fix time or uptime. We
answer on business days, `[hours and time zone — owner decides]`, on a best-effort basis. Target, not commitment —
`[N business hours — owner decides]`.

8.3. **Support does not** answer for model providers or Telegram, restore data without a backup, or administer the
Customer server without a section 7 service.

8.4. An SLA with service credits is **not offered** until there is 24/7 on-call and measured availability.

## 9. Data and personal data

9.1. **Where data lives.** On the Customer server: sessions, Claude Code logs, settings, Pult people (files with mode
0600). In a Space at the Provider — on the Provider's server, in the space's isolated folder.

9.2. **What leaves the server**: to the model provider — what the agent reads while working; to Telegram — answers
and notifications to people with a role; to the Customer's mail server — login codes, if enabled. The Pult replaces
keys and passwords in messages with a placeholder before the agent sees them — this lowers the risk but does **not
guarantee** a secret never reaches the model.

9.3. **Legal roles.** For data the Customer puts in the Pult, the Customer is the controller/operator; the Provider
processes on the Customer's behalf (Spaces at the Provider only). **To confirm with the lawyer.**

9.4. **Russia, Federal Law 152-FZ.** The Provider does **not** guarantee 152-FZ compliance. Known facts: requests to
a foreign model are a cross-border transfer, and the Pult neither limits nor flags it; personal data of Russian
citizens needs a server in Russia, notice to Roskomnadzor and data-subject consent before work starts, done by the
Customer as operator; Russian models (GigaChat, YandexGPT via the Customer's gateway) are **not verified** with a
real gateway and keys ([`RU-MODELS.md`](RU-MODELS.md)). Until the lawyer answers, do **not** load Russian customers'
personal data into the Pult.

9.5. **EU, GDPR.** The Provider does **not** claim GDPR compliance. There is no DPA and no sub-processor list. Model
providers process data under their own terms. Until the company is registered in the EU (section 13), do not load
EU residents' personal data into a Space at the Provider.

9.6. **Model training.** The Provider does not use Customer data to train models. Whether a model provider does
depends on its terms and the Customer's account settings.

9.7. **Export.** On the Customer server the data is already the Customer's. From a Space — an archive of the space
folder on request within `[N days — owner decides]`.

## 10. Termination and refunds

10.1. The **Customer** may cancel at any time by message to support. Access lasts until the end of the paid period.

10.2. The **Provider** may terminate: with `[30 days — owner decides]` notice without cause; immediately for a breach
of the user agreement, a model provider's terms or the law.

10.3. **Refunds** — `[owner decides]`. Options: paid periods are non-refundable except where the law requires; or a
refund for unused full months; and in all cases, if the Provider terminates without the Customer's fault, it refunds
the unused prepayment and spend reserve.

10.4. **Data after termination.** On the Customer server it stays with the Customer. In a Space — an archive on
request within `[N days]`, then deletion (`pult-tenant destroy`).

10.5. Consumer rights may apply to individuals — **to confirm with the lawyer** whether this offer is for
individuals or only for businesses.

## 11. Liability

11.1. The Pult and services are provided "as is". The Provider is not liable for model answers and actions,
including ones a person confirmed with "Yes"; outages of model providers, Telegram, hosting and networks;
consequences of commands run by the Customer's people; indirect damages and lost profit.

11.2. **Liability cap** — the amount the Customer paid the Provider in the last `[3 / 6 / 12 months — owner
decides]`. The cap does not apply to wilful misconduct or where the law forbids it.

11.3. The Customer is responsible for its keys, its people and their roles, and for following model providers' terms.

## 12. Changes to the offer

The Provider publishes a new revision. For existing customers it applies from the next paid period. A Customer who
disagrees cancels under 10.1.

## 13. Governing law and disputes

13.1. **Russia.** The Provider is a Russian sole proprietor `[company details]`. Russian law applies. First a written
claim, answered within `[30 days — owner decides]`; then the court at the Provider's location `[to confirm]`.

13.2. **International customers.** **Note: after the company is registered in Spain.** Until then this offer is not
made to international customers. Governing law, courts, taxes and GDPR documents (DPA, sub-processors) follow
registration and legal review.

13.3. An invalid clause does not void the others.

## 14. Company details

`[placeholder: name, registration numbers, address for claims, bank. Real details are never added to this public
repository.]`

Sources for the structure — see the table "Откуда взято" above (same URLs; checked 17 November 2026; Notion MSA and
OpenAI Services Agreement could not be opened and were not used).
