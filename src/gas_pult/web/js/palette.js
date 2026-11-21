// Палитра ⌘K на ПК (разбор Gemini 21.11, №15, приём 1 — как в Linear): окно по центру — чаты, проекты, действия;
// ↑↓ — выбор, Enter — открыть, Esc — закрыть. На телефоне поиск остаётся в панели (navSearch).
const CSS = `.pal-bg { position: fixed; inset: 0; z-index: 40; background: rgba(17,17,16,.35); display: flex; justify-content: center;
  align-items: flex-start; padding-top: 14vh; }
.pal { width: min(600px, calc(100vw - 32px)); max-height: 60vh; display: flex; flex-direction: column; background: var(--bg-surface);
  border: 1px solid var(--border-subtle); border-radius: 12px; box-shadow: 0 12px 40px rgba(0,0,0,.25); overflow: hidden; }
.pal input { border: 0; border-bottom: 1px solid var(--border-subtle); padding: 14px 16px; font: inherit; font-size: 16px;
  background: transparent; color: var(--text-primary); outline: none; }
.pal ul { list-style: none; margin: 0; padding: 6px; overflow-y: auto; }
.pal li { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--radius-sm); cursor: pointer; }
.pal li.on { background: var(--bg-subtle); } .pal li small { margin-left: auto; color: var(--text-muted); font-size: 12px; }
.pal .grp { padding: 8px 10px 4px; font-size: 11.5px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
  color: var(--text-muted); cursor: default; } .pal .none { color: var(--text-muted); cursor: default; }`;

function items() {
  // действия — тот же список, что у поиска в панели (palCmds в ядре): один источник команд, не второй поиск
  const acts = palCmds().map((c) => ({ g: "Действия", t: c.label, i: c.icon, kw: c.kw || "", run: c.run }));
  const chats = sessions.map((s) => ({ g: "Чаты", t: s.title || s.name, i: "chat", sub: ST[s.status]?.label || "", run: () => openSession(s.id) }));
  const projs = (projData?.projects || []).filter((p) => !p.archived)
    .map((p) => ({ g: "Проекты", t: p.name, i: "folder", run: () => openProject(p.id) }));
  return { acts, rest: [...chats, ...projs] };
}

export function open() {
  document.querySelector(".pal-bg")?.remove();
  if (!document.getElementById("palCss")) document.head.insertAdjacentHTML("beforeend", `<style id="palCss">${CSS}</style>`);
  const { acts, rest } = items();                    // пусто — сначала действия (быстрые), поиск — сначала чаты
  const bg = document.createElement("div"); bg.className = "pal-bg";
  bg.innerHTML = '<div class="pal" role="dialog" aria-label="Поиск и действия"><input type="search" placeholder="Чаты, проекты, действия…" '
    + 'aria-label="Поиск по чатам, проектам и действиям" autocomplete="off"><ul role="listbox"></ul></div>';
  document.body.append(bg);
  const inp = bg.querySelector("input"), ul = bg.querySelector("ul");
  let shown = [], at = 0;
  const close = () => bg.remove();
  const go = (x) => { close(); x?.run(); };
  const draw = () => {
    const q = inp.value.trim().toLowerCase();
    shown = (q ? [...rest, ...acts].filter((x) => (x.t + " " + (x.kw || "")).toLowerCase().includes(q)) : [...acts, ...rest]).slice(0, 40);
    at = Math.min(at, Math.max(0, shown.length - 1));
    let g = "";
    ul.innerHTML = shown.length ? shown.map((x, i) => (x.g !== g ? `<li class="grp" aria-hidden="true">${esc((g = x.g))}</li>` : "")
      + `<li role="option" data-k="${i}" class="${i === at ? "on" : ""}" aria-selected="${i === at}">${ic(x.i, "s16")}<span>${esc(x.t)}</span>`
      + `${x.sub ? `<small>${esc(x.sub)}</small>` : ""}</li>`).join("") : '<li class="none">Ничего не нашлось</li>';
    ul.querySelector("li.on")?.scrollIntoView({ block: "nearest" });
  };
  inp.oninput = () => { at = 0; draw(); };
  inp.onkeydown = (e) => {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); at = Math.min(at + 1, shown.length - 1); draw(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); at = Math.max(at - 1, 0); draw(); }
    else if (e.key === "Enter") { e.preventDefault(); go(shown[at]); }
  };
  ul.onclick = (e) => { const li = e.target.closest("li[data-k]"); if (li) go(shown[+li.dataset.k]); };
  bg.onclick = (e) => { if (e.target === bg) close(); };
  draw(); inp.focus();
}
