// «Ход работы» в чате (штаб 26.11, аудит Atoms п. 2): под строкой статуса («Выполняет действие 13 с») — сворачиваемый
// список шагов агента в текущем ходе: что делает, удачно ли, сколько шло. Строка статуса остаётся как была — список
// только добавлен. Данные — /api/steps (журнал Claude Code, секреты скрыты на сервере, steps.py); запрос — только пока
// список раскрыт, раз в 3 с. Без режима разработчика шаги — общими словами (тот же словарь, что у строки статуса),
// без команд и путей. Кому: участникам пространства; владельцу — только если включит сам (localStorage stepLog=1,
// экран владельца не меняем); по фокус-ссылке и наблюдателю — нет (/api/steps им сервер не отдаёт); демо — ?demo&steps.
// Часть по требованию (#191): в ядре — пустые контейнеры #actLog / #sLog и вызов init().

const L = {
  ru: { title: "Ход работы", none: "Шагов пока нет", ok: "готово", err: "ошибка", run: "идёт" },
  en: { title: "Progress", none: "No steps yet", ok: "done", err: "error", run: "running" },
};
const CSS = `
.steplog { margin: 4px 0 8px; font-size: calc(13px * var(--fz, 1)); color: var(--text-secondary); }
.steplog > button { display: inline-flex; align-items: center; gap: 6px; min-height: 32px; padding: 0 10px; border: 0;
  border-radius: 8px; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.steplog > button:hover { background: var(--bg-hover, rgba(128,128,128,.08)); }
.steplog > button .i { width: 16px; height: 16px; transition: transform .15s; }
.steplog[data-open="1"] > button .i { transform: rotate(90deg); }
.steplog ol { list-style: none; margin: 4px 0 0; padding: 0 0 0 10px; border-left: 2px solid var(--border, rgba(128,128,128,.25)); }
.steplog li { display: flex; gap: 8px; align-items: baseline; padding: 3px 0 3px 8px; }
.steplog li .w { flex: 1; min-width: 0; overflow-wrap: anywhere; color: var(--text-primary); }
.steplog li .s { flex: none; font-size: calc(12px * var(--fz, 1)); }
.steplog li.bad .s { color: var(--status-error, #C2361A); }
@media (prefers-reduced-motion: reduce) { .steplog > button .i { transition: none; } }
`;
const store = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
const PLACES = [["act", "actLog", () => (typeof current !== "undefined" ? current : null)],
  ["sAct", "sLog", () => (typeof SIM !== "undefined" && SIM.on ? SIM.w : null)]];
let timer = null;

export function allowed(role, focus) {
  return !focus && role !== "viewer" && (role !== "owner" || store("stepLog") === "1");
}

function label(s) {                                   // без режима разработчика — общими словами, как строка статуса
  if (dev()) return s.what || s.tool;
  const t = T(sKey({ phase: "working", tool: s.tool }));
  return t && !t.startsWith("status.") ? t : T("status.works");
}

async function load(box, w) {
  const t = L[LANG] || L.ru;
  let d; try { d = await api("/api/steps?w=" + encodeURIComponent(w)); } catch (e) { return; }
  const turn = d.turns?.[0], steps = turn?.steps || [];
  const html = steps.length ? steps.map((s) => {
    const st = s.ok === false ? t.err : s.ok ? t.ok + (s.dur >= 1 ? " · " + Math.round(s.dur) + " с" : "") : t.run;
    return `<li class="${s.ok === false ? "bad" : ""}"><span class="w">${esc(label(s))}</span><span class="s">${esc(st)}</span></li>`;
  }).join("") : `<li><span class="w">${esc(t.none)}</span></li>`;
  const ol = box.querySelector("ol"); if (ol && ol.innerHTML !== html) ol.innerHTML = html;
}

function tick() {
  const t = L[LANG] || L.ru, ok = (typeof DEMO !== "undefined" && DEMO) || allowed(meta?.role, typeof FOCUS !== "undefined" && FOCUS);   // роль известна не сразу
  for (const [rowId, boxId, win] of PLACES) {
    const row = document.getElementById(rowId), box = document.getElementById(boxId), w = win();
    if (!box) continue;
    const on = !!(ok && row && w && !row.classList.contains("off"));
    if (box.hidden === on) box.hidden = !on;
    if (!on) continue;
    if (box.dataset.w !== w) { box.dataset.w = w; box.dataset.open = ""; box.innerHTML = ""; }
    if (!box.firstChild) {
      box.innerHTML = `<button type="button" aria-expanded="false">${ic("chevron")}<span>${esc(t.title)}</span></button>`;
      box.firstChild.onclick = () => {
        const open = box.dataset.open !== "1";
        box.dataset.open = open ? "1" : ""; box.firstChild.setAttribute("aria-expanded", String(open));
        box.querySelector("ol")?.remove();
        if (open) { box.insertAdjacentHTML("beforeend", "<ol></ol>"); load(box, box.dataset.w); }
      };
    }
    if (box.dataset.open === "1" && !document.hidden && (box.__n = (box.__n || 0) + 1) % 3 === 0) load(box, w);
  }
}

export function init() {
  if (timer) return;
  if (!document.getElementById("slStyle")) {
    const st = document.createElement("style"); st.id = "slStyle"; st.textContent = CSS; document.head.append(st);
  }
  tick(); timer = setInterval(tick, 1000);
}
