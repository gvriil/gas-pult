// Фото в ленте и просмотр — часть по требованию (#191). Владелец 16.11: «возможность просмотра фотографий в
// чат-интерфейсе». В сообщениях пути к картинкам («Файл из панели: …», «Файл из Telegram: …») → миниатюры под
// текстом; нажал — полноэкранный просмотр: щипок до 5×, перетаскивание, двойной тап (1× ↔ 2,5×), свайп вниз —
// закрыть, свайп вбок и стрелки — соседние фото сообщения; компьютер — колесо, Esc. Картинки отдаёт /api/media
// (только владельцу, только из inbox и с Диска); тег <img> не умеет заголовок входа Mini App — грузим fetch → blob.

const IMG_RE = /(\/[^\s"'<>]+?\.(?:jpe?g|png|webp|gif|heic))(?=[\s"'<>),.;]|$)/gi;
const cache = new Map();                             // путь → blob: URL (на время жизни страницы)

async function mediaUrl(path) {
  if (cache.has(path)) return cache.get(path);
  let url;
  if (typeof DEMO !== "undefined" && DEMO) {          // демо: картинка-заглушка без сервера
    const c = Object.assign(document.createElement("canvas"), { width: 1200, height: 800 });
    const g = c.getContext("2d"), h = [...path].reduce((a, ch) => a + ch.charCodeAt(0), 0) % 360;
    g.fillStyle = `hsl(${h} 60% 55%)`; g.fillRect(0, 0, 1200, 800);
    g.fillStyle = "#fff"; g.font = "bold 64px sans-serif"; g.fillText(path.split("/").pop(), 60, 420);
    url = c.toDataURL("image/jpeg", 0.8);
  } else {
    const r = await fetch("/api/media?p=" + encodeURIComponent(path), {
      credentials: "same-origin", headers: { "X-Telegram-Init-Data": tg?.initData || "" } });
    if (!r.ok) throw new Error("ошибка " + r.status);
    url = URL.createObjectURL(await r.blob());
  }
  cache.set(path, url);
  return url;
}

function decorate(msg) {                            // миниатюры под текстом сообщения — один раз
  if (msg.dataset.media) return;
  const paths = [...new Set([...(msg.querySelector(".bubble, .md") || msg).textContent.matchAll(IMG_RE)].map((m) => m[1]))];
  msg.dataset.media = paths.length ? "1" : "0";
  if (!paths.length) return;
  const box = document.createElement("div"); box.className = "att-imgs";
  box.style.cssText = "display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 2px;justify-content:inherit";
  for (const p of paths) {
    const im = document.createElement("img");
    im.alt = p.split("/").pop(); im.dataset.path = p; im.loading = "lazy";
    im.style.cssText = "width:120px;height:120px;object-fit:cover;border-radius:10px;cursor:zoom-in;background:var(--bg-subtle)";
    mediaUrl(p).then((u) => { im.src = u; }, () => { im.remove(); });   // нет доступа или файла — без миниатюры
    box.append(im);
  }
  (msg.querySelector(".bubble") || msg).after(box);
}

function scan() {
  if (typeof meta !== "undefined" && meta?.role && meta.role !== "owner") return;   // /api/media — только владельцу
  for (const m of document.querySelectorAll("#content .msg:not([data-media]):not(.skel)")) decorate(m);
}
new MutationObserver(() => scan()).observe(document.body, { childList: true, subtree: true });
scan();
document.addEventListener("click", (e) => {
  const im = e.target.closest?.(".att-imgs img");
  if (!im) return;
  e.preventDefault();
  const all = [...im.closest(".att-imgs").querySelectorAll("img")];
  lightbox(all.map((x) => x.dataset.path), all.indexOf(im));
});

// ---------- полноэкранный просмотр ----------
let lb = null;
function lightbox(paths, i) {
  lbClose();
  const el = lb = document.createElement("div");
  el.className = "lb"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Просмотр фото");
  el.style.cssText = "position:fixed;inset:0;z-index:40;background:rgb(0 0 0/.92);touch-action:none;overflow:hidden;"
    + "display:grid;place-items:center;user-select:none";
  el.innerHTML = `<img alt="" style="max-width:100%;max-height:100%;transform-origin:0 0;will-change:transform">
    <button class="lb-x" aria-label="Закрыть" style="position:absolute;top:calc(10px + env(safe-area-inset-top));right:10px;width:44px;height:44px;border:0;border-radius:22px;background:rgb(255 255 255/.15);color:#fff;font-size:22px">✕</button>
    <span class="lb-n" style="position:absolute;bottom:calc(14px + env(safe-area-inset-bottom));left:0;right:0;text-align:center;color:#ddd;font:13px system-ui"></span>`;
  document.body.append(el);
  const img = el.querySelector("img"), n = el.querySelector(".lb-n");
  let s = 1, x = 0, y = 0, at = i;
  const apply = () => { img.style.transform = `translate(${x}px, ${y}px) scale(${s})`; };
  const reset = () => { s = 1; x = 0; y = 0; img.style.transformOrigin = "50% 50%"; apply(); };
  const show = (k) => {
    at = (k + paths.length) % paths.length; reset(); img.src = "";
    mediaUrl(paths[at]).then((u) => { if (lb === el) img.src = u; });
    n.textContent = paths.length > 1 ? `${at + 1} из ${paths.length}` : "";
  };
  const zoomAt = (ns, cx, cy) => {                   // масштаб вокруг точки экрана (cx, cy)
    ns = Math.max(1, Math.min(5, ns));
    const r = img.getBoundingClientRect(), ox = cx - r.left, oy = cy - r.top, k = ns / s;
    x += ox - ox * k; y += oy - oy * k; s = ns;
    if (s === 1) { x = 0; y = 0; }
    apply();
  };
  img.style.transformOrigin = "0 0";
  show(i);
  const pts = new Map(); let pinch = null, swipe = null, lastTap = 0;
  el.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".lb-x")) return;
    try { el.setPointerCapture(e.pointerId); } catch (_) {}
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 1) swipe = { x: e.clientX, y: e.clientY, t: Date.now() };
    if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), s }; swipe = null; }
  });
  el.addEventListener("pointermove", (e) => {
    const p = pts.get(e.pointerId); if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2 && pinch) {
      const [a, b] = [...pts.values()];
      zoomAt(pinch.s * Math.hypot(a.x - b.x, a.y - b.y) / pinch.d, (a.x + b.x) / 2, (a.y + b.y) / 2);
    } else if (pts.size === 1 && s > 1) { x += dx; y += dy; apply(); }      // увеличено — двигаем
    else if (pts.size === 1 && swipe) { img.style.transform = `translate(${e.clientX - swipe.x}px, ${Math.max(0, e.clientY - swipe.y)}px)`; }
  });
  const up = (e) => {
    const was = pts.size; pts.delete(e.pointerId);
    if (pts.size < 2) pinch = null;
    if (was !== 1 || !swipe) return;
    const dx = e.clientX - swipe.x, dy = e.clientY - swipe.y, quick = Date.now() - swipe.t < 300;
    swipe = null;
    if (s === 1 && dy > 120) return lbClose();                                  // вниз — закрыть
    if (s === 1 && Math.abs(dx) > 80 && Math.abs(dx) > Math.abs(dy) && paths.length > 1) return show(at + (dx < 0 ? 1 : -1));
    if (s === 1) apply();
    if (quick && Math.hypot(dx, dy) < 10) {                                       // двойной тап: 1× ↔ 2,5×
      const now = Date.now();
      if (now - lastTap < 320) { lastTap = 0; s > 1 ? reset() : zoomAt(2.5, e.clientX, e.clientY); }
      else lastTap = now;
    }
  };
  el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
  el.addEventListener("wheel", (e) => { e.preventDefault(); zoomAt(s * Math.exp(-e.deltaY / 300), e.clientX, e.clientY); }, { passive: false });
  el.addEventListener("gesturestart", (e) => e.preventDefault());              // iOS: жест — наш, страница не зумится
  el.querySelector(".lb-x").onclick = lbClose;
  el.keys = (e) => {
    if (e.key === "Escape") lbClose();
    else if (e.key === "ArrowRight" && paths.length > 1) show(at + 1);
    else if (e.key === "ArrowLeft" && paths.length > 1) show(at - 1);
  };
  addEventListener("keydown", el.keys);
  try { tg?.BackButton?.show(); tg?.BackButton?.onClick(lbClose); } catch (_) {}
}
function lbClose() {
  if (!lb) return;
  removeEventListener("keydown", lb.keys); lb.remove(); lb = null;
  try { tg?.BackButton?.offClick(lbClose); } catch (_) {}
}

Object.assign(window, { lightbox, lbClose, mediaScan: scan });
