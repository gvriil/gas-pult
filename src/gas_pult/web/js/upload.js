// Загрузка файлов из панели — часть интерфейса по требованию (#191): грузится при первом прикреплённом файле.
// Фото — сжать на телефоне перед отправкой (владелец 15.11: «почему так долго загружается фото»: 223 КБ шли 52 с,
// ~4 КБ/с — узкое место — сеть телефона). Длинная сторона ≤ 1920 px, JPEG 0,85; скриншоты PNG — тоже. Не стало
// меньше, GIF, не картинка, «без сжатия» — исходный файл.
const SHRINK_SIDE = 1920, SHRINK_Q = 0.85;
async function shrinkImage(f) {
  if (!/^image\/(jpeg|png|webp|heic|heif)$/i.test(f.type || "") || !window.createImageBitmap) return f;
  try {
    const bmp = await createImageBitmap(f, { imageOrientation: "from-image" });
    const k = Math.min(1, SHRINK_SIDE / Math.max(bmp.width, bmp.height));
    if (k === 1 && f.size < 400 * 1024) { bmp.close?.(); return f; }
    const c = Object.assign(document.createElement("canvas"), { width: Math.round(bmp.width * k), height: Math.round(bmp.height * k) });
    const g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);   // прозрачный PNG — на белом
    g.drawImage(bmp, 0, 0, c.width, c.height); bmp.close?.();
    const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", SHRINK_Q));
    if (!blob || blob.size >= f.size) return f;
    return new File([blob], (f.name || "photo").replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
  } catch (_) { return f; }                          // не разобрал (редкий формат) — исходный файл
}
// Загрузка с прогрессом (XHR: у fetch нет upload.onprogress). Заголовки — как у api(): вход Mini App или фокус-ссылки.
function uploadXhr(url, blob, headers, onprog) {
  if (DEMO) return demoUpload(blob, onprog);
  return new Promise((ok, no) => {
    const x = new XMLHttpRequest(); x.open("POST", url);
    const h = { ...(FOCUS ? { "X-Gp-Focus": "1" } : { "X-Telegram-Init-Data": tg?.initData || "" }), "Content-Type": blob.type || "application/octet-stream", ...headers };
    for (const [k, v] of Object.entries(h)) x.setRequestHeader(k, v);
    x.upload.onprogress = (e) => e.lengthComputable && onprog(e.loaded / e.total);
    x.onload = () => { let d = {}; try { d = JSON.parse(x.responseText || "{}"); } catch (_) {}
      x.status < 300 ? ok(d) : no(Object.assign(new Error(d.error || "ошибка " + x.status), { status: x.status })); };
    x.onerror = () => no(Object.assign(new Error("нет связи"), { net: true }));
    x.send(blob);
  });
}
async function demoUpload(blob, onprog) {              // демо: «сеть» 64 КБ/с, путь — как у сервера
  window.__demoUploads = [...(window.__demoUploads || []), blob.size];
  for (let k = 1; k <= 5; k++) { await new Promise((r) => setTimeout(r, Math.min(400, blob.size / 64 / 5))); onprog(k / 5); }
  return { path: "/home/u/drive/demo/Входящие/" + (blob.name || "file") };
}

Object.assign(window, { shrinkImage, uploadXhr, demoUpload });
