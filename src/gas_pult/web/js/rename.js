// «Переименовать» (GAS-13 п.3; пользователь фокус-ссылки 19.11: «моя сессия называется „papasan-1329 · Ожидание
// формулировки задачи“… мне нужно переименовать вторую часть»). Главное — название чата: своё хранится на сервере
// (/api/title), автоматика его не перетирает, «Сбросить» возвращает авто-тему. Имя окна (papasan-1329) — мелкой
// строкой ниже; менять его может владелец, не по фокус-ссылке.

const red = (t) => { $("renErr").textContent = t; $("renErr").style.color = "var(--status-danger)"; };

export function rename(s) {
  const winOk = !FOCUS && meta?.role !== "viewer";
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.rename");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Название чата</h3>
    <div class="field" style="margin:4px 16px 0"><input id="renName" maxlength="60" autocomplete="off" value="${esc(s.title || "")}" placeholder="О чём этот чат"></div>
    <p class="note" id="renErr" style="margin:6px 16px 0">${s.title_own ? "Ваше название — автоматика его не меняет." : "Сейчас — автоматическое, по разговору."}</p>
    ${winOk ? `<p class="note" style="margin:6px 16px 0">Имя окна: <b>${esc(s.name)}</b> · <a href="#" id="renWin">изменить</a></p>` : ""}
    <div class="row2">${s.title_own ? '<button class="btn ghost" id="renReset">Сбросить</button>' : '<button class="btn ghost" data-close>Отмена</button>'}<button class="btn" id="renOk">Сохранить</button></div></div>`;
  document.body.append(bg);
  const inp = $("renName"); inp.focus(); inp.select();
  const done = async (title) => {
    bg.remove(); toast(title ? "Теперь: " + title : "Название — снова автоматическое"); haptic("notificationOccurred", "success");
    await refresh(); if (s.id === current) paintSession(cur());
  };
  const put = async (title) => {
    try { const d = await api("/api/title", { w: s.id, title }); await done(d.own ? d.title : ""); } catch (e) { red(e.message); }
  };
  $("renOk").onclick = () => { const t = inp.value.trim().replace(/\s+/g, " "); if (!t) return red("Напишите название или нажмите «Сбросить»"); put(t); };
  $("renReset")?.addEventListener("click", () => put(""));
  $("renWin")?.addEventListener("click", (e) => { e.preventDefault(); bg.remove(); renameWindow(s); });
  inp.onkeydown = (e) => { if (e.key === "Enter") $("renOk").click(); if (e.key === "Escape") bg.remove(); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
}

function renameWindow(s) {                            // имя окна tmux — как раньше: до 40 знаков, без «:» и «.»
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.rename");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Имя окна</h3>
    <div class="field" style="margin:4px 16px 0"><input id="renName" maxlength="40" autocomplete="off" value="${esc(s.name)}"></div>
    <p class="note" id="renErr" style="margin:6px 16px 0">До 40 знаков, без «:» и «.» — по нему сессию находит бот.</p>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="renOk">Сохранить</button></div></div>`;
  document.body.append(bg);
  const inp = $("renName"); inp.focus(); inp.select();
  const save = async () => {
    const name = inp.value.trim().replace(/\s+/g, " ");
    if (!name || /[:.]/.test(name)) return red("До 40 знаков, без «:» и «.»");
    try { await api("/api/rename", { w: s.id, name }); bg.remove(); toast("Теперь: " + name); haptic("notificationOccurred", "success"); await refresh(); if (s.id === current) paintSession(cur()); }
    catch (e) { red(e.message); }
  };
  $("renOk").onclick = save;
  inp.onkeydown = (e) => { if (e.key === "Enter") save(); if (e.key === "Escape") bg.remove(); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
}
