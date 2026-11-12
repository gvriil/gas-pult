const LANGS = ["ru", "en"];
let LANG = LANGS.includes(params.get("lang")) ? params.get("lang") : LANGS.includes(store("lang")) ? store("lang") : "ru";
// Словарь (план UX, пункт 10): прошлый — из localStorage сразу, список не ждёт сети; свежий — в фоне.
let DICT = (() => { try { return JSON.parse(localStorage.getItem("dict:" + LANG) || "{}"); } catch (e) { return {}; } })();
let dictReady = Object.keys(DICT).length ? Promise.resolve() : loadDict(LANG);
if (Object.keys(DICT).length) loadDict(LANG);
async function loadDict(lang) {
  try {
    const r = await fetch("i18n/" + lang + ".json", { cache: "no-store" });
    if (r.ok && lang === LANG) { const t = await r.text(); DICT = JSON.parse(t); store("dict:" + lang, t); }
  }
  catch (e) { /* без словаря — русские строки полного режима; простой режим покажет ключи до следующей попытки */ }
  document.documentElement.lang = LANG;
}
function T(k, v) { let s = DICT[k] ?? k; for (const x in v || {}) s = s.split("{" + x + "}").join(String(v[x])); return s; }
const L = (k, ru) => ((SIM.on || (view === "login" && LANG === "en")) && DICT[k] ? T(k) : ru);   // общее: помощник, переходы
const LL = (k, ru) => (LANG === "en" && DICT[k] ? T(k) : ru);                                   // первый экран
