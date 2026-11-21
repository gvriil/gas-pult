// «Новый проект» (панель чатов → «Проекты» → «+»): лист с названием, папкой, инструкциями и моделью — часть, а не
// ядро (перенесено из index.html, GAS-38). В пространстве клиента (meta.space) проект — папка home/projects/<название>
// (кириллица можно): поле «Папка» и выбор модели скрыты, инструкции — до 4000 знаков (space_projects.INSTR_MAX).

export function open() {
  closePop(); navOpen(false);
  if (meta?.role === "viewer") return;
  const sp = !!meta?.space, root = projData?.new_root || "~/projects", models = sp ? [] : meta?.models || [];
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.new-project");
  bg.innerHTML = `<div class="sheet" role="dialog" aria-labelledby="npTitle"><h3 id="npTitle">Новый проект</h3><div style="padding:4px 16px 0">
    <div class="field"><label for="npName">Название</label><input id="npName" maxlength="80" autocomplete="off" placeholder="например, Магазин книг"></div>
    <div class="field"${sp ? " hidden" : ""}><label for="npFolder">Папка <span class="opt">· в ${esc(root)}</span></label><input id="npFolder" maxlength="41" autocapitalize="off" spellcheck="false" autocomplete="off" placeholder="из названия">
      <p class="note" style="margin:4px 2px 0">Латиница в нижнем регистре, цифры, дефис. Сразу с git.</p></div>
    <div class="field"><label for="npInstr">Инструкции <span class="opt">· необязательно, в CLAUDE.md</span></label><textarea id="npInstr" rows="3"${sp ? ' maxlength="4000"' : ""} placeholder="Как работать в этом проекте: тон, правила, что важно"></textarea></div>
    ${models.length ? `<div class="field"><label>Модель по умолчанию</label><div class="np-models" role="group" aria-label="Модель по умолчанию">${["", ...models].map((m) => `<button type="button" data-npm="${esc(m)}" aria-pressed="${m === "" ? "true" : "false"}">${esc(m || "Как у пульта")}</button>`).join("")}</div></div>` : ""}
    <p class="note" id="npErr" role="alert" style="margin:0 2px;color:var(--status-danger)" hidden></p></div>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="npOk">Создать</button></div></div>`;
  document.body.append(bg);
  const name = $("npName"), folder = $("npFolder"); let own = false, model = "";
  name.focus();
  name.oninput = () => { if (!own) folder.value = npFolder(name.value); };
  folder.oninput = () => { own = !!folder.value.trim(); };
  const bad = (t) => { $("npErr").textContent = t; $("npErr").hidden = false; };
  const save = () => busy($("npOk"), "Создаю…", async () => {
    const n = name.value.trim(), f = folder.value.trim().toLowerCase() || npFolder(n);
    if (!n) { name.focus(); return bad("Назовите проект."); }
    if (!sp && !/^[a-z0-9][a-z0-9-]{1,40}$/.test(f)) { folder.focus(); return bad("Имя папки: латиница в нижнем регистре, цифры, дефис (2–41 знак)."); }
    try {
      const d = await api("/api/project/new", { name: n, folder: f, instructions: $("npInstr").value, model });
      bg.remove(); haptic("notificationOccurred", "success");
      projData = await api("/api/projects").catch(() => projData);
      if (!projOf(d.id)) (projData ||= { projects: [] }).projects = [...(projData.projects || []), { id: d.id, name: d.name, folder: d.folder, path: d.path, origin: "new", chats: 0 }];
      NAV.exp.add(d.id); store("lastProj", d.id);
      newChat(d.id); toast(`Проект «${d.name}» создан — напишите первое сообщение`, 3500);
    } catch (e) { bad(e.message); }
  });
  $("npOk").onclick = save;
  bg.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); save(); } if (e.key === "Escape") bg.remove(); });
  bg.addEventListener("click", (e) => {
    const m = e.target.closest("[data-npm]");
    if (m) { model = m.dataset.npm; bg.querySelectorAll("[data-npm]").forEach((x) => x.setAttribute("aria-pressed", String(x === m))); return; }
    if (e.target === bg || e.target.closest("[data-close]")) bg.remove();
  });
}
