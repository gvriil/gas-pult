// Запись не теряется (владелец 22.11: «запись обрывается, когда телефон блокируют или выходят из приложения»).
// Часть по требованию (#191): ядро (toggleMic) пишет MediaRecorder кусками по 10 с, эта часть шлёт каждый кусок на
// сервер сразу (POST /api/rec/chunk, recparts.py) — оборвётся запись, на сервере уже есть всё, кроме последних секунд.
// Пока идёт запись — своя блокировка экрана (Wake Lock), по «Стоп» она снимается. Обрыв (блокировка, звонок,
// свернули) — новый отрезок в той же записи, когда человек вернётся; «Стоп» — сервер склеивает текст отрезков.
// Страницу закрыли посреди записи — при следующем открытии «Запись прервалась»: распознать то, что дошло, или удалить.
// iPhone: панель в фоне не пишет (Safari и Telegram останавливают микрофон) — один раз честная подсказка.

export const SLICE = 10000;
const KEY = "rec:live", HINT = "rec:ios-hint";
const IOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
const keep = (v) => { try { v ? localStorage.setItem(KEY, JSON.stringify(v)) : localStorage.removeItem(KEY); } catch (e) { /* только удобство */ } };
const kept = () => { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } };

// Сеанс записи: push(кусок) — на сервер по порядку с повтором; next() — новый отрезок после обрыва;
// finish() — {job} распознавания (ошибка — запись уходит целиком, как раньше); drop() — отмена.
export function session(type) {
  const rid = crypto.randomUUID?.() || Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  const S = { rid, seg: 0, seq: 0, ok: true, q: Promise.resolve(), lock: null, at: Date.now() };
  const save = () => keep({ rid, seg: S.seg, seq: S.seq, at: S.at, last: Date.now() });
  async function send(seg, seq, blob) {
    for (let i = 0; i < 5; i++) {
      try { await api(`/api/rec/chunk?id=${encodeURIComponent(rid)}&seg=${seg}&seq=${seq}`, blob, (blob.type || type || "audio/webm").split(";")[0]); return; }
      catch (e) { if (!e.net) break; await sleep(2000 * (i + 1)); }   // нет сети — ждём и повторяем; ответ сервера — нет
    }
    S.ok = false;                                     // кусок не дошёл: по «Стоп» запись уйдёт целиком из памяти
  }
  S.push = (blob) => { const seg = S.seg, seq = S.seq++; S.q = S.q.then(() => send(seg, seq, blob)); save(); };
  S.next = () => { S.seg++; S.seq = 0; save(); wake(S, true); };
  S.finish = async () => {
    await S.q; wake(S, false); keep(null);
    if (!S.ok) throw new Error("не все куски записи дошли");
    return api("/api/rec/finish", { id: rid });
  };
  S.drop = () => { wake(S, false); keep(null); S.q.then(() => api("/api/rec/drop", { id: rid }).catch(() => {})); };
  S.wake = () => wake(S, true);
  save(); wake(S, true); hint();
  return S;
}

// Своя блокировка экрана на время записи (панель держит общую, пока открыта, — keepAwake ядра; эта снимается по «Стоп»)
async function wake(S, on) {
  try {
    if (!on) { await S.lock?.release(); S.lock = null; return; }
    if (navigator.wakeLock && !document.hidden && (!S.lock || S.lock.released)) S.lock = await navigator.wakeLock.request("screen");
  } catch (e) { /* нет Wake Lock (старый браузер, режим энергосбережения) — запись всё равно идёт кусками */ }
}

// iPhone: один раз — честно, что в фоне запись останавливается, и как записать длинную встречу
function hint() {
  if (!IOS && !params.has("ios")) return;
  try { if (localStorage.getItem(HINT)) return; localStorage.setItem(HINT, "1"); } catch (e) { /* покажем ещё раз — не страшно */ }
  toast("На iPhone при блокировке запись останавливается. Для длинной встречи: Диктофон → Поделиться → Гаврила", 9000);
}

// «Запись прервалась на N с, продолжаю» — в строке записи ядра и вслух для экранного диктора
export function resumed(bar, ms) {
  const s = Math.max(1, Math.round(ms / 1000)), txt = s < 120 ? s + " с" : Math.round(s / 60) + " мин";
  const t = `Запись прервалась на ${txt}, продолжаю`;
  let n = bar?.querySelector(".gap");
  if (bar && !n) { n = document.createElement("span"); n.className = "gap"; n.setAttribute("role", "status"); bar.querySelector(".t")?.after(n); }
  if (n) { n.textContent = t; clearTimeout(n.tm); n.tm = setTimeout(() => n.remove(), 6000); }
  toast(t, 4000);
}

// Страницу закрыли посреди записи (выгрузили из памяти, закрыли Mini App): то, что дошло, — на сервере
export async function leftover() {
  const k = kept(); if (!k?.rid) return;
  let st; try { st = await api("/api/rec/status?id=" + encodeURIComponent(k.rid)); } catch (e) { return keep(null); }
  if (!st.have) return keep(null);
  const min = Math.max(1, Math.round(st.have * SLICE / 60000));
  sheet("Запись прервалась", [
    { info: true, icon: "mic", label: `На сервере ~${min} мин записи`, sub: new Date(k.at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) + " · дошло всё, кроме последних секунд" },
    { label: "Распознать и вставить текст", icon: "check", run: () => { const b = new Blob([], { type: st.ctype || "audio/webm" }); b.rec = { finish: () => { keep(null); return api("/api/rec/finish", { id: k.rid }); } }; sttRun(b, false); } },
    { label: "Удалить запись", icon: "trash", danger: true, run: () => { keep(null); api("/api/rec/drop", { id: k.rid }).catch(() => {}); toast("Запись удалена", 2500); } },
  ]);
}

document.head.insertAdjacentHTML("beforeend", `<style>
  .recbar .gap { flex: 1; min-width: 0; font-size: calc(12px * var(--fz, 1)); line-height: 1.25; color: var(--text-primary); }
  .recbar:has(.gap) canvas { display: none; }
</style>`);
