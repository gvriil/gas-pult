// Голос: запись не теряется, длинная — распознаётся в фоне (GAS-34; владелец 18.11: «надо не потерять запись… долгую
// запись, чтобы справлялся микрофончик»). Запись сначала ложится в IndexedDB этого браузера, потом уходит на сервер
// фоновым заданием (POST /api/stt?job=1 → id; сервер тоже хранит файл, пока нет текста). Панель опрашивает
// /api/stt/job, лимита 90 с нет. Текст получен — запись удаляется и здесь, и на сервере. Вкладку закрыли, связь
// пропала, сервер не справился — запись остаётся; при следующем открытии панели — «Есть нераспознанная запись».

const DB = "gas-pult", ST = "voice", POLL = 1500, MAX_WAIT = 40 * 60 * 1000;

function idb() {
  return new Promise((ok, no) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(ST);
    r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error);
  });
}
async function tx(mode, fn) {
  const db = await idb();
  return new Promise((ok, no) => { const t = db.transaction(ST, mode), s = t.objectStore(ST), r = fn(s); t.oncomplete = () => ok(r?.result); t.onerror = () => no(t.error); });
}
const put = (id, v) => tx("readwrite", (s) => s.put(v, id)).catch(() => {});
const del = (id) => tx("readwrite", (s) => s.delete(id)).catch(() => {});
const all = () => tx("readonly", (s) => s.getAll()).catch(() => []);
const flag = async () => { try { (await all()).length ? localStorage.setItem("vj", "1") : localStorage.removeItem("vj"); } catch (e) {} };
const sleep = (ms, signal) => new Promise((ok, no) => { const t = setTimeout(ok, ms); signal?.addEventListener("abort", () => { clearTimeout(t); no(new Error("прервано")); }); });

// Распознать запись: хранится здесь до текста; ошибка сервера — с его причиной (запись остаётся и там, и здесь).
const ids = new WeakMap();                           // «Повторить» той же записи — та же запись здесь, без копий
export async function sttJob(blob, signal) {
  const id = ids.get(blob) || crypto.randomUUID?.() || String(Date.now()); ids.set(blob, id);
  await put(id, { blob, type: blob.type, at: Date.now() }); flag();
  const { job } = await api("/api/stt?job=1", blob, blob.type, null, signal);
  const t0 = Date.now();
  while (Date.now() - t0 < MAX_WAIT) {
    await sleep(POLL, signal);
    let r; try { r = await api("/api/stt/job?id=" + encodeURIComponent(job)); } catch (e) { if (e.net) continue; throw e; }
    if (r.state === "done") { await del(id); flag(); return { text: r.text, fallback: r.fallback }; }
    if (r.state === "fail") throw Object.assign(new Error(r.error || "распознать не вышло"), { kept: true });
  }
  throw Object.assign(new Error("распознавание идёт слишком долго — запись сохранена, повторите позже"), { kept: true });
}

// При открытии панели: остались нераспознанные записи — предложить распознать (или удалить).
export async function leftover() {
  const xs = await all(); if (!xs.length) return flag();
  const db = await idb(), keys = await new Promise((ok) => { const r = db.transaction(ST).objectStore(ST).getAllKeys(); r.onsuccess = () => ok(r.result); r.onerror = () => ok([]); });
  const min = (x) => Math.max(1, Math.round((x.blob?.size || 0) / 4000 / 60));   // ~32 кбит/с — оценка длины
  sheet("Есть нераспознанная запись", xs.map((x, i) => ({
    label: new Date(x.at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) + " · ~" + min(x) + " мин",
    icon: "mic", sub: "распознать и вставить текст в поле",
    run: async () => { await del(keys[i]); flag(); sttRun(x.blob, false); },
  })).concat([{ label: "Удалить все записи", icon: "trash", danger: true, run: async () => { for (const k of keys) await del(k); flag(); toast("Записи удалены", 2500); } }]));
}
