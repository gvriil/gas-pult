// «Люди» (владелец и админ), карточка человека и «Команда» — вынесено из ядра index.html (лимит 770 КБ, тест
// test_ui_parts). Грузится по требованию: part("people"). Общие функции ядра (api, sheet, helpSheet, ROLE…) — глобальные.

export async function peopleSheet() {
  let d; try { d = await api("/api/people"); } catch (e) { return toast(e.message, 4000); }
  helpSheet("settings.people");
  // Список — имя, роль, когда входил (Gemini №12: «ID, страна, IP — в карточке»). Подробности — в карточке человека.
  const when = (t) => new Date(t * 1000).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
  sheet("Команда и права", [
    ...d.people.map((p) => ({
      label: p.name || (p.username ? "@" + p.username : p.role === "owner" ? "Вы" : "Без имени"), icon: p.country?.mismatch ? "warn" : "place",
      sub: ROLE[p.role] + (p.kind === "guest" ? " · без Telegram" : "") + (p.last?.at ? " · входил " + when(p.last.at) : " · ещё не входил"),
      run: () => p.role !== "owner" && personSheet({ ...p, geoip: d.geoip, attribution: d.attribution }) })),
    ...(meta?.role === "owner" && UI?.can_team ? [{ label: "Что видят сотрудники", icon: "tasks", sub: "разделы и возможности по ролям", run: () => teamSheet() }] : []),
    { info: true, label: "Как добавить человека", icon: "plus", sub: "пусть откроет панель и нажмёт «Войти через Telegram» — бот спросит вас, кем его пустить" }]);
}
// Подробности о человеке (было в строке списка): ID, @имя, пространство, устройство, условия, страна и IP — в карточке
const personDetails = (p) => ROLE[p.role] + (p.kind === "guest" ? " · без Telegram" : "") + (p.tenant ? " · пространство " + p.tenant : "") + (p.last?.at ? " · вошёл " + new Date(p.last.at * 1000).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) + ", " + p.last.device : "") + (p.username ? " · @" + p.username : "") + (p.terms && p.terms.version === meta?.terms?.version ? " · условия приняты " + new Date(p.terms.at * 1000).toLocaleDateString("ru-RU") : " · условия не приняты") + countryLine(p.country, p.geoip);

export function personSheet(p) {
  const set = (role) => api("/api/people/role", { id: p.id, role }).then(() => toast("Роль: " + ROLE[role])).catch((e) => toast(e.message, 4000));
  const until = (days) => api("/api/people/access", { id: p.id, days }).then(() => toast(days ? `Доступ продлён на ${days} дней` : "Доступ бессрочный")).catch((e) => toast(e.message, 4000));
  const owner = meta?.role === "owner";
  helpSheet("settings.person");
  if (!owner && p.role === "admin") return sheet(p.name || "ID " + p.id, [{ info: true, icon: "lock", label: "Админ", sub: "менять админа может только владелец" }]);
  const exp = p.access_until ? new Date(p.access_until * 1000).toLocaleDateString("ru-RU") : "";
  sheet(p.name || "ID " + p.id, [
    ...(owner || dev() ? [{ info: true, icon: "place", label: "ID " + p.id, sub: personDetails(p).replace(/^[^·]*· /, "") }] : []),
    ...(p.geoip && (owner || dev()) ? [{ info: true, icon: "globe", label: "Страна по IP", sub: (p.attribution || "IP Geolocation by DB-IP") + " · db-ip.com, CC BY 4.0" }] : []),
    { info: true, icon: "wait", label: exp ? (p.access_until * 1000 < Date.now() ? "Доступ закончился " : "Доступ до ") + exp : "Доступ бессрочный" },
    ...(exp ? [{ label: "Продлить на 30 дней от сегодня", icon: "plus", run: () => until(30) }, { label: "Сделать бессрочным", icon: "check", run: () => until(0) }]
      : [{ label: "Ограничить доступ: 30 дней", icon: "wait", run: () => until(30) }]),
    ...(p.role === "member" ? [{ label: "Что видит в пульте", icon: "tasks", sub: "разделы и возможности — экран «Команда»", run: () => teamSheet(p.id) }] : []),
    ...(p.tenant ? [{ label: "Ссылка для входа на другое устройство", icon: "phone", sub: "одноразовая, 24 часа: QR, ссылка и код", run: () => personDevice(p) }] : []),
    { label: "Участник", icon: "chat", on: p.role === "member", sub: "писать в сессии, отвечать, новые сессии — без «Выполнить» и ключей", run: () => set("member") },
    { label: "Наблюдатель", icon: "eye", on: p.role === "viewer", sub: "только смотреть", run: () => set("viewer") },
    ...(owner && p.kind !== "guest" && !p.tenant ? [{ label: "Админ", icon: "key", on: p.role === "admin", sub: "приглашает людей, меняет роли, продлевает доступ, помогает в пространствах — без ключей, денег и команд на сервере", run: () => set("admin") }] : []),
    { label: "Отключить", icon: "power", danger: true, sub: "доступ прекратится сразу: вход перестанет работать на всех устройствах", run: () => confirmDanger(`Отключить ${p.name || "ID " + p.id}? Доступ к пульту прекратится сразу.`, () => api("/api/people/remove", { id: p.id }).then(() => toast("Отключён: " + (p.name || "ID " + p.id))).catch((e) => toast(e.message, 4000))) },
  ]);
}

export async function teamSheet(uid) {
  let d; try { d = await api("/api/team"); } catch (e) { return toast(e.message, 4000); }
  const p = uid == null ? null : d.people.find((x) => x.id === uid);
  const caps = p ? (p.own_caps ?? p.ceiling) : (d.staff_caps ?? d.catalog.caps.map((c) => c.id));
  const secs = p ? (p.own_sections ?? p.sections) : d.sections;
  const name = (x) => x.name || (x.username ? "@" + x.username : "ID " + x.id);
  const save = (body) => api("/api/team", body).then(() => { toast("Сохранено"); teamSheet(uid); }).catch((e) => toast(e.message, 4000));
  const flip = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const who = p ? { id: uid } : {};
  helpSheet("settings.team");
  sheet(p ? "Команда: " + name(p) : "Команда", [
    { info: true, icon: "lock", label: p ? (p.own_caps ? "Свои настройки — поверх общих" : "Как у всех сотрудников") : "Для всех сотрудников",
      sub: p ? "что видит этот человек; права проверяет сервер" : d.staff_caps == null ? "пока не задано — сотрудники видят всё, как раньше" : "что видят участники пульта; права проверяет сервер" },
    { head: "Разделы над чатом" },
    ...d.catalog.sections.map((x) => ({ label: x.title, on: secs.includes(x.id), run: () => save({ ...who, sections: flip(secs, x.id) }) })),
    { head: "Возможности" },
    ...d.catalog.caps.map((c) => ({ label: c.title, on: caps.includes(c.id), sub: c.ready ? (c.dev ? "инженерное" : "") : "готовится", run: () => save({ ...who, caps: flip(caps, c.id) }) })),
    ...(p ? [{ label: "Как у всех сотрудников", icon: "refresh", sub: "убрать свои настройки этого человека", run: () => save({ id: uid, reset: true }) }]
      : [{ head: "Сотрудники" }, ...d.people.map((x) => ({ label: name(x), icon: "place", sub: x.own_caps ? "свои настройки" : "как у всех", run: () => teamSheet(x.id) })),
         ...(d.people.length ? [] : [{ info: true, icon: "plus", label: "Сотрудников пока нет", sub: "участники появятся здесь — «Настройки» → «Люди»" }])]),
  ]);
}

function countryLine(c, geoip) {
  if (!c?.chosen) return " · страна не выбрана";
  const ip = !geoip ? "нет базы" : c.ip_cc || "нет данных";
  return ` · страна ${c.chosen}, номер ${c.phone ? c.phone_cc || "?" : "не подтверждён"}, IP ${ip}` + (c.mismatch ? " — признаки расходятся" : "");
}
