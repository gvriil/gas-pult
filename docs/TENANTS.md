# Демо-пространства

Пространство — изолированное место для демо клиенту: свой пользователь Linux, своя папка с лимитом диска, свои
процессы с лимитами памяти и процессора, своя папка Claude Code и своя модель с ключом API. Пространства не видят
друг друга, домашнюю папку владельца и его подписку Claude.

Создаёт, бэкапит и убирает пространства **владелец сервера** скриптами через `sudo`. Пульт сам `sudo` для этого не
вызывает и вызвать не может: ему разрешено только открывать окна в пространствах (`sudo -u pult_t_<slug> tmux …`).
Пока настройка не сделана (шаг 1), функция выключена и пульт работает как раньше.

## Устройство

| Что | Где | Права |
|---|---|---|
| Пользователь | `pult_t_<slug>` (дефис в имени → `_`), без входа в систему (`nologin`, без пароля), своя группа + группа `pult-tenants` | — |
| Папка | `/srv/pult/tenants/<slug>/` — точка монтирования своего образа ext4 `/srv/pult/images/<slug>.img` (по умолчанию 2 ГБ: это и есть лимит диска; `nodev,nosuid`) | 0710 `pult_t_<slug>:pult-ro` |
| `home/` | домашняя папка (`HOME`) | 0700 |
| `config/claude/` | `CLAUDE_CONFIG_DIR` пространства: вход, MCP, настройки | 0710, внутри — 0600 |
| `config/claude/projects/` | журналы Claude Code: пульт читает расход и ответы | 2750 `…:pult-ro` |
| `config/profiles/<id>.json` | настройки профиля модели с ключом (`claude --settings …`) | 0600 |
| `run/tmux/default` | сокет своего сервера tmux | папка 0700 |
| `tmp/ data/ inbox/ trash/` | временные файлы, данные, входящие, корзина пространства | 0700 |
| `secrets.json` | ключи API пространства | 0600 |
| `audit.jsonl` | журнал действий владельца (create, key, login, backup, destroy) | 0640 `root:pult-ro` |
| `usage/`, `budget.json` | расход и дневной бюджет (USD) | 2750 / 0640 `…:pult-ro` |
| `tenant.json` | описание: название, юрисдикция, вид панели (`persona`), профиль модели | 0644 root |

- **Процессы.** Служба `pult_t_<slug>.service` держит сервер tmux пространства (`tmux -D -S <сокет>`) от имени его
  пользователя, в slice `pult_t_<slug>.slice` с `MemoryMax=1G`, `CPUQuota=80%`, `TasksMax=128`. Окна, которые пульт
  открывает через сокет, — дети этого сервера: они в том же slice и в той же песочнице (`ProtectHome=yes` — `/home`
  не видна совсем, `ProtectProc=invisible` — чужие процессы не видны, `ProtectSystem=strict` — писать можно только в
  свою папку, `NoNewPrivileges`, `PrivateTmp`).
- **Журналы — пульту.** Claude Code пишет журналы с правами 0600; таймер `pult-share-<slug>.timer` раз в 30 секунд от
  имени пользователя пространства открывает группе `pult-ro` чтение файлов в `config/claude/projects` (больше ничего).
  Пульт входит в `pult-ro` и читает их без `sudo`; писать в пространство он не может.
- **sudo.** Одно правило `/etc/sudoers.d/gas-pult-tenants`: пользователь пульта → `sudo -u` любого пользователя группы
  `pult-tenants`, без пароля, только `tmux` и `claude`. Аргументы tmux не сужены: sudo-rs (Ubuntu 25.10+) не знает
  шаблонов в аргументах, и сужение ничего бы не дало — право открыть окно уже есть право выполнить в нём любую команду
  от имени пространства. От имени владельца, root или других пользователей правило ничего не разрешает.
- **Модель.** По умолчанию — первый профиль с ключом API, разрешённый в юрисдикции пространства (`models.allowed`):
  OpenRouter, затем GLM, DeepSeek; для `--jurisdiction RU` — только российские профили (GigaChat, YandexGPT через
  шлюз клиента, `docs/RU-MODELS.md`). Ключ задаётся для пространства отдельно (`pult-tenant key`), ключи пульта не
  используются. Подписка владельца (`~/.claude`, `.credentials.json`) **не копируется никогда** — это личная подписка
  (условия Consumer). Вход в Claude внутри пространства — только вручную владельцем и только для его тестов
  (`pult-tenant login`).

## Что делает владелец

Команды ниже — с сервера пульта, из папки репозитория (`cd ~/projects/gas-pult`), от имени вашего пользователя
(того, под кем работает пульт), с `sudo`. Каждую можно сначала прогнать с `--dry-run`: она только покажет шаги.

### Шаг 0. Проверить домашнюю папку

`stat -c %a ~` → должно быть `750` или `700` (у прочих — никаких прав). Иначе пространства смогут заглянуть в неё.
Исправить: `chmod 0750 ~`. Откат: `chmod <прежние права> ~`. Шаг 1 проверяет это сам (`--fix-home` — исправит).

### Шаг 1. Настройка — один раз

`sudo bin/pult-tenant-setup install --dry-run`, затем `sudo bin/pult-tenant-setup install`.

Что делает: группы `pult-ro` и `pult-tenants`, ваш пользователь — в `pult-ro`; папки `/srv/pult/{tenants,images,
backups,trash,etc-backup}`; правило sudo (проверяется `visudo -cf` до установки и `visudo -c` после — при ошибке
правило не ставится или сразу убирается; прежний файл, если был, — в `/srv/pult/etc-backup/`); отметка
`/srv/pult/tenants/.enabled` (по ней пульт понимает, что функция включена).

После — перезапустить пульт, чтобы он получил группу: `systemctl --user restart gas-pult gas-pult-webapp`.

Проверить: `sudo bin/pult-tenant-setup status`; `id` — в списке групп есть `pult-ro`.

Откат: `sudo bin/pult-tenant-setup uninstall` (убирает правило sudo и отметку — пульт снова работает без
пространств); группы — `sudo gpasswd -d <ваш пользователь> pult-ro`, `sudo groupdel pult-tenants`, `sudo groupdel pult-ro`
(после того как убраны все пространства); папку `/srv/pult` — `sudo rm -r /srv/pult` (после того как бэкапы не нужны).

### Шаг 2. Чужие процессы не видны (hidepid) — по желанию, рекомендуется

`sudo bin/pult-tenant-setup hidepid --dry-run`, затем `sudo bin/pult-tenant-setup hidepid`.

Что делает: бэкап `/etc/fstab` в `/srv/pult/etc-backup/`, строка `proc /proc proc defaults,hidepid=invisible,gid=<pult-ro>
0 0` в fstab и `mount -o remount` для `/proc` сразу. Процессы других пользователей становятся невидимы всем, кроме
root и группы `pult-ro` (пульту они нужны: он узнаёт Claude в окнах по процессам). Окна пространств скрыты от
чужих и без этого шага (`ProtectProc=invisible` в их службе) — шаг 2 закрывает то же для всего остального.

Если в fstab уже есть своя строка `/proc` — скрипт остановится; поправьте её вручную.

Проверить: `grep hidepid /proc/mounts`; от имени пространства `sudo -u pult_t_<slug> ps -e` показывает только его
процессы.

Риск: у части служб (polkit, некоторые мониторинги) с `hidepid` бывают сбои. Заметили — откат.

Откат: `sudo bin/pult-tenant-setup hidepid-off` (бэкап fstab, строка gas-pult убирается, `mount -o
remount,hidepid=off /proc`). Или вручную: вернуть fstab из `/srv/pult/etc-backup/fstab.<время>` и `sudo mount -o
remount,hidepid=off /proc`.

### Шаг 3. Создать пространство

`sudo bin/pult-tenant create demo --title "Демо для кафе" --jurisdiction NL --dry-run`, затем без `--dry-run`.

Параметры: `--jurisdiction` (страна клиента, `RU` — только российские профили), `--persona` (вид панели по
умолчанию: `business_owner`, `point_admin`, `project_manager`, `student`, `developer`; по умолчанию
`business_owner`), `--profile` (профиль модели), `--budget` (USD в день, по умолчанию 3), `--size` (диск, по
умолчанию `2G`).

Что делает (каждый шаг сначала проверяет, не сделан ли он — повторный запуск безопасен и чинит права):
1. `useradd --system --user-group --groups pult-tenants --shell /usr/sbin/nologin` (без пароля и домашней папки в `/home`).
2. Образ: `fallocate -l 2G /srv/pult/images/demo.img`, `mkfs.ext4`.
3. Бэкап `/etc/fstab`, строка `… /srv/pult/tenants/demo ext4 loop,nodev,nosuid,nofail 0 2`, `mount`.
4. Папки и файлы с правами из таблицы выше; `tenant.json`, `budget.json`, пустой `secrets.json`.
5. `pult_t_demo.slice`, `pult_t_demo.service`, `pult-share-demo.{service,timer}` в `/etc/systemd/system`,
   `systemctl enable --now`.

Повторный `create` с другими параметрами — обновляет описание (название, юрисдикцию, вид, профиль, бюджет).

Проверить: `sudo bin/pult-tenant list` (смонтирован, tmux `active`, занято на диске);
`systemctl status pult_t_demo.service`; `systemctl show pult_t_demo.slice -p MemoryMax -p CPUQuotaPerSecUSec -p TasksMax`;
доступ пульта — от вашего пользователя `sudo -n -u pult_t_demo /usr/bin/tmux -S /srv/pult/tenants/demo/run/tmux/default -V`
(печатает версию tmux, пароль не спрашивает).

Откат — шаг 6 (`destroy`).

### Шаг 4. Claude Code и ключ модели

Claude Code в пространстве — свой, в его домашней папке (ваш `~/.local/bin/claude` пространству не виден):
`sudo -u pult_t_demo env HOME=/srv/pult/tenants/demo/home bash -c 'curl -fsSL https://claude.ai/install.sh | bash'`.
Он займёт около 200 МБ диска пространства. Откат: `sudo rm -rf /srv/pult/tenants/demo/home/.local/{bin,share}/claude`.

Ключ: `sudo bin/pult-tenant key demo openrouter --default` — ключ вводится скрыто (или со стандартного ввода).
Для GigaChat и YandexGPT — ещё `--base-url https://<ваш шлюз>`. Ключ ложится в `secrets.json` и
`config/profiles/<профиль>.json` пространства (0600, владелец — пользователь пространства); `audit.jsonl` получает
запись с последними 4 знаками ключа. Откат: удалить файл профиля и ключ из `secrets.json` (или `destroy`).

### Шаг 5. Вход в Claude в пространстве — только для ваших тестов

По умолчанию пространство работает на ключе API. Если вам самому нужно проверить в нём Claude по подписке:
`sudo bin/pult-tenant login demo` — скрипт покажет предупреждение («только для ваших тестов; подписку не давать
клиентам и не копировать её токены»), попросит ввести «да» и подскажет команду, которой вы **сами** войдёте
(`/login` в окне пространства). Ничего не копируется. Для юрисдикции RU вход недоступен.
Откат: `sudo bin/pult-tenant logout demo` — удаляет вход (`.credentials.json` пространства) и возвращает профиль с
ключом API.

### Шаг 6. Бэкап и удаление

- Бэкап: `sudo bin/pult-tenant backup demo` → `/srv/pult/backups/demo-<время>.tar.gz` (0600; без `tmp/` и `run/`).
- Убрать: `sudo bin/pult-tenant destroy demo` (спросит имя пространства; без терминала — `--yes demo`). Порядок:
  **бэкап** → служба и таймер остановлены и выключены → размонтировать → строка из fstab (с бэкапом fstab) → образ и
  юниты — в `/srv/pult/trash/demo-<время>/` → пользователь заблокирован (`usermod --lock --expiredate 1`). Ничего не
  удаляется.
- Вернуть из корзины: перенести `demo.img` обратно в `/srv/pult/images/`, юниты — в `/etc/systemd/system/`,
  `sudo usermod --unlock --expiredate '' pult_t_demo`, затем `sudo bin/pult-tenant create demo` (вернёт строку fstab,
  смонтирует и запустит).
- Удалить навсегда: `sudo bin/pult-tenant purge demo-<время> --yes demo` — второе подтверждение; удаляет запись
  корзины и пользователя. Бэкап в `/srv/pult/backups/` остаётся — удалите его сами, когда не нужен.

## Проверка изоляции

`sudo bin/pult-tenant check <A> <B>` — из пространства A пытается:

- прочитать папку B, её `tenant.json`, `secrets.json`, `audit.jsonl`, домашнюю папку, папку Claude и журналы;
- подключиться к сокету tmux B;
- увидеть процессы B (`/proc/<pid>`) и прочитать их окружение (`/proc/<pid>/environ`), окружение процесса владельца;
- прочитать домашнюю папку владельца (`--owner`, по умолчанию — кто запустил sudo) и его файлы (`.claude/.credentials.json`,
  `.claude.json`, токен и ключи пульта, ключ SSH — те, что есть).

Каждая попытка должна получить отказ. Попытки идут из двух мест: **«окно A»** — внутри песочницы службы tmux A
(`nsenter` в её пространство имён монтирования, затем `runuser`) — ровно то, что видит Claude Code в окне; **«права
файлов»** — просто `runuser -u pult_t_<A>`, без песочницы. Контроль — A читает свою домашнюю папку: не вышло — проверка
ничего не доказывает. Нет цели (служба A не запущена, у B нет сокета) — «не проверено», это тоже ПРОВАЛ. Если у B нет
ни одного процесса, на время проверки от имени B запускается `sleep 60`.

Итог — таблица ОК / ПРОВАЛ / ВНИМАНИЕ и код возврата: 0 — везде отказ, 1 — есть ПРОВАЛ, 2 — неверный вызов.
ВНИМАНИЕ — процесс B виден «без песочницы», когда не сделан шаг 2 (hidepid); после шага 2 это ПРОВАЛ.

Запускайте в обе стороны (`check A B` и `check B A`) после создания пространств, после шага 2 и после обновлений
системы. Проверка ничего не меняет. В CI та же логика проверяется моком (`tests/test_tenant_check.py`), а сама проба —
по-настоящему, на папках и сокете без прав.

## Как пульт работает с пространством

- `tenants.enabled()` — есть ли отметка настройки; нет — пульт работает как раньше, `sudo` не вызывается.
- `tenants.status(check=True)` — список пространств (slug, название, юрисдикция, вид, профиль, бюджет) и `ready`:
  пускает ли sudo без пароля (`sudo -n -u … tmux -S … -V`, кэш 60 секунд).
- `tenants.new_window(slug, name)` — окно с Claude Code в пространстве: `sudo -n -u pult_t_<slug> tmux -S <сокет>
  new-window …` с командой `CLAUDE_CONFIG_DIR=<папка> claude --settings <папка>/config/profiles/<профиль>.json`.
  Остальная работа с окном — тот же `tmux.Tmux`, только с префиксом `sudo -n -u … tmux -S …` (`tenants.tmux_of`).

Экран пространств в панели (переключатель, «Войти как…») — отдельная задача.

## Чего здесь нет

- Сетевой изоляции: пространство ходит в интернет, как и пульт (к поставщику модели). Порты на `127.0.0.1` других
  пользователей пространству доступны — в том числе панель пульта (с тем же входом, что снаружи). Закрыть — строкой
  `IPAddressDeny=localhost` в службе пространства (решение владельца: ломает шлюз модели на этом же сервере).
- Расход пространства в лимитах пульта: бюджет хранится, а пауза по нему — в следующих частях.
