// «Отзыв» (штаб 21.11): одна кнопка — в «Настройках» («Система и справка») и в поиске. Текст (голос — кнопкой
// диктовки на клавиатуре телефона) и снимок экрана по желанию → сервер кладёт в feedback/ и в задачи штаба
// (feedback.py). Экран, с которого пишут, — только id (как в учёте функций), без содержимого.

const MAX = 1600;                                    // снимок — до 1600 px по длинной стороне, JPEG: меньше 4 МБ

export function shrink(file) {
  return new Promise((ok, no) => {
    const img = new Image(), url = URL.createObjectURL(file);
    img.onload = () => {
      const k = Math.min(1, MAX / Math.max(img.width, img.height));
      const c = Object.assign(document.createElement("canvas"), { width: Math.round(img.width * k), height: Math.round(img.height * k) });
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url); ok(c.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = () => { URL.revokeObjectURL(url); no(new Error("это не картинка")); };
    img.src = url;
  });
}

export function open() {
  const screen = (typeof USE !== "undefined" && USE.cur) || "";
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = "sheet.feedback";
  bg.innerHTML = `<div class="sheet" role="dialog" aria-labelledby="fbTitle"><h3 id="fbTitle">Отзыв</h3>
    <p class="note" style="margin:4px 16px 10px">Что не так или что улучшить? Сообщение уйдёт команде пульта. Голосом — кнопка микрофона на клавиатуре.</p>
    <div class="field" style="margin:0 16px"><label for="fbText">Ваш отзыв</label><textarea id="fbText" rows="5" maxlength="4000" placeholder="Например: не нашёл, где поменять время брифинга"></textarea></div>
    <div style="margin:10px 16px 0;display:flex;align-items:center;gap:10px"><button class="btn ghost sm" id="fbPick">${ic("image")} Приложить снимок экрана</button>
      <img id="fbPrev" alt="" hidden style="width:44px;height:44px;object-fit:cover;border-radius:var(--radius-sm);border:1px solid var(--border-subtle)">
      <input type="file" id="fbFile" accept="image/*" hidden></div>
    <p class="note" id="fbMsg" role="status" style="margin:8px 16px 0"></p>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="fbGo">Отправить</button></div></div>`;
  document.body.append(bg);
  const $f = (s) => bg.querySelector(s), text = $f("#fbText"), file = $f("#fbFile");
  let shot = "";
  const close = () => bg.remove();
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) close(); });
  $f("#fbPick").onclick = () => file.click();
  file.onchange = async () => {
    const f = file.files?.[0]; if (!f) return;
    try { shot = await shrink(f); const p = $f("#fbPrev"); p.src = shot; p.hidden = false; $f("#fbMsg").textContent = ""; }
    catch (e) { shot = ""; $f("#fbMsg").textContent = e.message; }
  };
  $f("#fbGo").onclick = () => busy($f("#fbGo"), "Отправляю…", async () => {
    if (!text.value.trim() && !shot) { $f("#fbMsg").textContent = "Напишите пару слов или приложите снимок"; return text.focus(); }
    if (DEMO) { close(); return toast("В демо отзыв никуда не уходит", 3500); }
    try { await api("/api/feedback", { text: text.value, screen, shot }); close(); toast("Спасибо! Отзыв у команды", 3500); }
    catch (e) { $f("#fbMsg").textContent = e.message; }
  });
  setTimeout(() => text.focus(), 50);
}
