// «Перенести в проект…» (владелец 22.11: «очень важно добавить возможность переносить чаты из проекта в проект»).
// Шторка: поиск и список проектов (кроме проекта этого чата и архивных). Выбор — /api/chat/move: сервер переносит
// журнал в папку проекта и открывает чат там же с той же перепиской (--resume); человек остаётся в этом чате —
// панель переходит на новое окно. Идёт ход — сервер отвечает «перенесу, как только закончит» (фоновый цикл панели).

const word = (n) => { const f = agoPlural(n); return n + " " + (f === "one" ? "чат" : f === "few" ? "чата" : "чатов"); };

export async function open(s) {
  let list = projData?.projects;
  if (!list) { try { projData = await api("/api/projects"); list = projData.projects; } catch (e) { return toast(e.message, 4000); } }
  list = (list || []).filter((p) => p.id !== s.project && !p.archived && !p.space);
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.chat-move");
  bg.innerHTML = `<div class="sheet" role="dialog" aria-label="Перенести в проект"><h3>Перенести в проект</h3>
    <p class="note" style="margin:0 16px 8px">«${esc(s.title || s.name)}» продолжится в папке выбранного проекта — с той же перепиской.</p>
    <div class="field" style="margin:4px 16px 8px"><input id="mvQ" type="search" placeholder="Найти проект" autocomplete="off" aria-label="Найти проект"></div>
    <div id="mvList" role="list"></div>
    <button class="cancel" data-close>Отмена</button></div>`;
  document.body.append(bg);
  const box = bg.querySelector("#mvList"), q = bg.querySelector("#mvQ");
  const paint = () => {
    const t = q.value.trim().toLowerCase();
    const hit = list.filter((p) => !t || [p.name, p.folder, p.last_title].some((x) => String(x || "").toLowerCase().includes(t)));
    box.innerHTML = hit.length ? hit.map((p) => `<button data-i="${esc(p.id)}" data-mv="${esc(p.id)}" role="listitem">${ic(p.origin?.startsWith("module:") ? "puzzle" : "folder")}<span>${esc(p.name)}<small>${esc(p.folder)} · ${esc(word(p.chats || 0))}</small></span></button>`).join("")
      : `<div class="empty">${list.length ? "Ничего не нашлось" : "Других проектов нет — создайте проект, потом переносите"}</div>`;
  };
  paint();
  q.oninput = paint;
  if (matchMedia("(pointer: fine)").matches) q.focus();      // на телефоне клавиатура не выпрыгивает сама
  bg.addEventListener("click", (e) => {
    const b = e.target.closest("[data-mv]");
    if (e.target === bg || e.target.closest("[data-close]")) return bg.remove();
    if (b) { bg.remove(); go(s, list.find((p) => p.id === b.dataset.mv)); }
  });
  bg.addEventListener("keydown", (e) => { if (e.key === "Escape") bg.remove(); });
}

async function go(s, p) {
  if (!p) return;
  const was = current === s.id;
  toast(`Переношу в «${p.name}»…`, 2500);
  let d;
  try { d = await api("/api/chat/move", { w: s.id, project: p.id }); }
  catch (e) { return toast("Не перенёс: " + e.message, 5000); }
  if (d.pending) return toast(`${d.text} — «${p.name}»`, 5000);
  haptic("notificationOccurred", d.failed ? "error" : "success");
  projDone = null; await refresh();
  if (was && d.id) openSession(d.id);                          // человек остаётся в том же чате — уже в новом окне
  toast(d.failed || `Чат теперь в проекте «${p.name}» · переписка та же`, d.failed ? 6000 : 3500);
}
