// Уведомления на телефон и компьютер (владелец 20.11: «чтобы все уведомления приходили на телефон; главное — понятно,
// управляемо, как включается и отключается»). Включить на этом устройстве — подписка Web Push (сервер будит браузер,
// даже когда панель закрыта); «Проверить» — тестовое уведомление на все ваши устройства; список устройств и «Отключить».
// iPhone: только у панели, добавленной на экран «Домой» (iOS 16.4+). В Telegram уведомления присылает бот.

const ios = () => /iPhone|iPad|iPod/.test(navigator.userAgent);
const standalone = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const can = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window && !tg?.initData;
const label = () => {
  const ua = navigator.userAgent;
  const os = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android" : /Mac/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : "Linux";
  const br = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "браузер";
  return `${os} · ${br}`;
};
const b64 = (s) => { const p = "=".repeat((4 - s.length % 4) % 4), r = atob((s + p).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(r, (c) => c.charCodeAt(0)); };

const devId = async (ep) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(ep)))]   // как ep_id на сервере
  .slice(0, 8).map((b) => b.toString(16).padStart(2, "0")).join("");

async function mine() {                               // подписка этого устройства (или null)
  if (!can() || DEMO) return null;
  const reg = await navigator.serviceWorker.register("/sw.js");
  return reg.pushManager.getSubscription();
}

async function enable() {
  if (DEMO) return toast("В демо уведомления не включаются", 3500);
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return toast("Уведомления не разрешены — включите их для этого сайта в настройках браузера", 5000);
  const reg = await navigator.serviceWorker.register("/sw.js"); await navigator.serviceWorker.ready;
  const { key } = await api("/api/push/key");
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(key) });
  await api("/api/push/subscribe", { sub: sub.toJSON(), label: label() });
  toast("Уведомления на это устройство включены", 3500);
}

// Часть B (notifyroute.py): куда — «На телефон / Telegram / Почта», о чём — события; одна точка доставки в боте.
const DEMO_PREFS = { owner: true, push: true, telegram: true, devices: 0, email: { can: true, addr: false, on: false },
  events: [["answer", "Ответы чатов"], ["dialog", "Чат ждёт вашего выбора"], ["error", "Сбои и лимиты"], ["brief", "Брифинг и расписание"], ["people", "Люди и вход"]]
    .map(([id, label]) => ({ id, label, on: true, email: id !== "answer" })) };

async function save(patch) {
  if (DEMO) { Object.assign(DEMO_PREFS, patch); if (patch.events) for (const [k, v] of Object.entries(patch.events)) DEMO_PREFS.events.find((e) => e.id === k).on = v; return DEMO_PREFS; }
  return api("/api/notify/prefs", patch);
}

function channels(p, deviceRow) {                    // «Куда присылать» и «О чём сообщать» — владельцу
  if (!p?.owner) return deviceRow ? [deviceRow] : [];
  const other = p.devices > 0 || p.email.on;
  const tgRow = { label: "Telegram", icon: "send", toggle: p.telegram,
    sub: p.telegram ? "сообщения бота" : "выключен — сообщения с кнопками решений всё равно придут туда",
    run: () => save({ telegram: !p.telegram }).then(() => { if (p.telegram && !other) toast("Других каналов нет — пока не включите телефон или почту, уведомления останутся в Telegram", 6000); open(); }, (e) => toast(e.message, 5000)) };
  const mailRow = !p.email.can ? null : !p.email.addr
    ? { label: "Почта", icon: "mail", sub: "сначала привяжите адрес", run: () => part("email").then(() => emailSheet()) }
    : { label: "Почта", icon: "mail", toggle: p.email.on, sub: "всё выбранное ниже, кроме ответов чатов", run: () => save({ email: !p.email.on }).then(open, (e) => toast(e.message, 5000)) };
  return [{ head: "Куда присылать" }, ...(deviceRow ? [deviceRow] : []), tgRow, ...(mailRow ? [mailRow] : []),
    { head: "О чём сообщать" },
    ...p.events.map((e) => ({ label: e.label, icon: { answer: "chat", dialog: "help", error: "warn", brief: "cal", people: "key" }[e.id] || "bell", toggle: e.on,
      run: () => save({ events: { [e.id]: !e.on } }).then(open, (x) => toast(x.message, 5000)) }))];
}

export async function open() {
  helpSheet("settings");
  let p = null;
  try { p = DEMO ? DEMO_PREFS : await api("/api/notify/prefs"); } catch (e) {}
  if (tg?.initData) return sheet("Уведомления", [{ info: true, icon: "bell", label: "Здесь, в Telegram, уведомления присылает бот", sub: "чтобы они приходили на телефон без Telegram — откройте Гаврилу в браузере и включите там" },
    { label: "Открыть в браузере", icon: "ext", sub: "iPhone: дальше «Поделиться» → «На экран «Домой»», откройте значком и включите", run: () => { try { tg.openLink(location.origin + "/"); } catch (e) { window.open(location.origin + "/", "_blank"); } } },
    ...channels(p, null)]);
  if (!can()) return sheet("Уведомления", [{ info: true, icon: "warn", label: "Этот браузер не умеет уведомления", sub: ios() && !standalone() ? "iPhone: «Поделиться» → «На экран «Домой»», откройте пульт оттуда и включите здесь" : "откройте панель в Chrome, Edge, Firefox или Safari" },
    ...channels(p, null)]);
  let devs = [], sub = null;
  try { [devs, sub] = await Promise.all([DEMO ? { devices: [] } : api("/api/push/devices").then((d) => d.devices), mine()]); } catch (e) { return toast(e.message, 5000); }
  const on = !!sub, here = on ? await devId(sub.endpoint) : "";
  // одна строка с тумблером справа (Gemini №11): включить — подписка; выключить — отписка этого устройства
  const deviceRow = { label: "На этом устройстве", icon: "phone", toggle: on, sub: on ? "даже когда панель закрыта"
    : ios() && !standalone() ? "iPhone: сначала «Поделиться» → «На экран «Домой»» и откройте Гаврилу оттуда" : "браузер спросит разрешение",
    run: on ? async () => { try { await api("/api/push/unsubscribe", { id: here }); await sub.unsubscribe(); } catch (e) {} toast("Выключено на этом устройстве", 3000); open(); }
      : () => enable().then(open, (e) => toast("Не вышло: " + e.message, 6000)) };
  sheet("Уведомления", [
    ...(p?.owner ? channels(p, deviceRow) : [deviceRow]),
    ...(on ? [{ sep: true }, { label: "Проверить", icon: "send", sub: "прислать тестовое уведомление на все ваши устройства", run: () => api("/api/push/test", {}).then((d) => toast(d.devices ? `Отправил на ${d.devices} ${plural(d.devices, ["устройство", "устройства", "устройств"])} — должно прийти за несколько секунд` : "Нет устройств с уведомлениями", 5000), (e) => toast(e.message, 5000)) }] : []),
    ...(devs.length ? [{ head: "Ваши устройства" }, ...devs.map((d) => ({ label: d.label + (d.id === here ? " — это устройство" : ""), icon: "phone", sub: (d.ok === false ? "последняя отправка не дошла · " : "") + "нажмите, чтобы отключить",
      run: () => api("/api/push/unsubscribe", { id: d.id }).then(() => { toast("«" + d.label + "» отключено", 3000); open(); }, (e) => toast(e.message, 5000)) }))] : []),
  ]);
}
