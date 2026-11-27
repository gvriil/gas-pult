// «Нет доступа к микрофону» — понятные шаги под браузер человека и «Попробовать снова» (владелец 24.11: «Permission
// not allowed», хочет, чтобы микрофон был разрешён всегда). Браузер запоминает «Разрешить» для сайта навсегда, если
// выбрать именно его в настройках сайта; разовое «Разрешить» в окне запроса Safari помнит только до закрытия вкладки.
// Шаги — по User-Agent и Telegram WebApp; ошибка браузера — мелко внизу, для отчёта.

const UA = navigator.userAgent;
const IOS = /iPhone|iPad|iPod/.test(UA) || (/Macintosh/.test(UA) && navigator.maxTouchPoints > 1);
const MAC = /Macintosh/.test(UA) && !IOS;
const CHROME = /Chrome\/|CriOS\//.test(UA) && !/Edg\//.test(UA);
const SAFARI = /Safari\//.test(UA) && !/Chrome\/|CriOS\/|FxiOS\/|Edg\//.test(UA);

function where() {
  if (typeof tg !== "undefined" && tg?.initData) return IOS ? "tg-ios" : MAC ? "tg-mac" : "tg";
  if (IOS) return CHROME ? "ios-chrome" : "ios-safari";
  if (MAC) return CHROME ? "mac-chrome" : SAFARI ? "mac-safari" : "other";
  return CHROME ? "chrome" : "other";
}

const HOST = location.host;
const STEPS = {
  "ios-safari": ["Слева в адресной строке нажмите «аА»", "«Настройки веб-сайта» → «Микрофон» → «Разрешить»",
                 "Для всех сайтов сразу: Настройки iPhone → Safari → Микрофон → «Разрешить»"],
  "ios-chrome": ["Настройки iPhone → Chrome → включите «Микрофон»", "Вернитесь сюда и нажмите «Попробовать снова»"],
  "mac-safari": ["Меню Safari → «Настройки…» → «Веб-сайты» → «Микрофон»", `Для ${HOST} выберите «Разрешить»`],
  "mac-chrome": ["Слева от адреса нажмите значок настроек сайта", "«Микрофон» → «Разрешить», затем обновите страницу",
                 "Если не помогло: Системные настройки → Конфиденциальность и безопасность → Микрофон → включите Google Chrome и перезапустите его"],
  chrome: ["Слева от адреса нажмите значок настроек сайта", "«Микрофон» → «Разрешить», затем обновите страницу"],
  "tg-ios": ["Настройки iPhone → Telegram → включите «Микрофон»", "Или откройте панель в Safari — там микрофон работает надёжнее"],
  "tg-mac": ["Telegram на Mac не даёт панели микрофон", "Откройте панель в Safari или Chrome — или диктуйте кнопкой микрофона на клавиатуре"],
  tg: ["Разрешите Telegram доступ к микрофону в настройках телефона", "Или откройте панель в браузере"],
  other: ["Откройте настройки этого сайта в браузере", "«Микрофон» → «Разрешить», затем обновите страницу"],
};

async function state() {
  try { return (await navigator.permissions.query({ name: "microphone" })).state; } catch (e) { return ""; }
}

// Ошибка getUserMedia → лист с шагами. ``retry`` — повторить то же действие (запись или диктовку).
export async function help(e, retry) {
  const name = e?.name || "";
  if (name === "NotFoundError" || name === "OverconstrainedError")
    return toast("Микрофон не найден — подключите его или выберите другой в настройках устройства", 6000);
  if (name === "NotReadableError" || name === "AbortError")
    return toast("Микрофон занят другой программой (звонок, запись) — закройте её и попробуйте снова", 6000);
  const w = where(), st = await state();
  const items = [{ head: st === "denied" ? "Микрофон для этого сайта запрещён — разрешите его один раз, и браузер запомнит" :
                         "Браузер не дал панели микрофон — разрешите его, и браузер запомнит" },
                 ...STEPS[w].map((s, i) => ({ label: `${i + 1}. ${s}`, info: true })),
                 { label: "Попробовать снова", icon: "mic", run: () => retry?.() },
                 { label: "Ответ браузера", sub: `${name || "ошибка"}: ${e?.message || ""}`.slice(0, 160), info: true }];
  sheet("Нет доступа к микрофону", items);
}
