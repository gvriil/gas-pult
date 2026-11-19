// «Шаги» (GAS-16, слой 7): что агент делал в чате — сообщение → инструменты (удачно ли, сколько шло, кусок
// результата) → ответ. Для отладки и доверия: видно, где ошибка — в просьбе, в документе или в инструменте.
// Данные — /api/steps (журнал Claude Code, секреты скрыты на сервере). Поиск — по всему: сообщению, шагам, ответу.

const when = (ts) => new Date(ts * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const secs = (n) => (n >= 60 ? Math.round(n / 60) + " мин" : Math.max(0, Math.round(n)) + " с");
let T = 0;

export function open(s) {
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.steps");
  bg.innerHTML = `<div class="sheet steps-sheet" role="dialog" aria-label="Шаги"><h3>Шаги · ${esc(s.title || s.name)}</h3>
    <div class="field" style="margin:4px 16px 8px"><input id="stQ" type="search" autocomplete="off" placeholder="Найти: файл, команда, ошибка…" aria-label="Поиск по шагам"></div>
    <div id="stList" class="steps-list" aria-live="polite"><div class="result wait">${ic("wait")}<span>Читаю журнал…</span></div></div>
    <button class="cancel" data-close>Закрыть</button></div>`;
  document.body.append(bg);
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
  const q = bg.querySelector("#stQ");
  q.addEventListener("input", () => { clearTimeout(T); T = setTimeout(() => load(s, q.value), 300); });
  q.addEventListener("keydown", (e) => { if (e.key === "Escape") bg.remove(); });
  load(s, "");
}

async function load(s, q) {
  const box = $("stList"); if (!box) return;
  let d;
  try { d = await api(`/api/steps?w=${encodeURIComponent(s.id)}&q=${encodeURIComponent(q.trim())}`); }
  catch (e) { box.innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; return; }
  if (!$("stList")) return;
  const turns = d.turns || [];
  if (!turns.length) { box.innerHTML = `<p class="note" style="margin:8px 16px">${esc(d.note || (q ? "Ничего не нашлось" : "Шагов пока нет — напишите агенту"))}</p>`; return; }
  box.innerHTML = turns.map((t) => {
    const bad = t.steps.filter((x) => x.ok === false).length;
    return `<details class="st-turn"${q ? " open" : ""}><summary><span class="st-when">${esc(when(t.at))} · ${esc(secs(t.dur))}${t.steps.length ? " · шагов " + t.steps.length : ""}${bad ? ` · <b class="st-bad">ошибок ${bad}</b>` : ""}</span><span class="st-prompt">${esc(t.prompt)}</span></summary>`
      + t.steps.map((x) => `<details class="st-step"><summary>${ic(x.ok === false ? "warn" : x.ok ? "check" : "wait", "s16")}<span>${esc(x.what)}</span><small>${x.dur != null ? esc(secs(x.dur)) : "идёт"}</small></summary>${x.out ? `<pre class="st-out">${esc(x.out)}</pre>` : ""}</details>`).join("")
      + (t.answer ? `<p class="st-answer">${ic("chat", "s16")}<span>${esc(t.answer)}</span></p>` : "") + "</details>";
  }).join("");
}

// Стиль — здесь, ядро не трогаем: одна строка на шаг, результат — по нажатию
document.head.insertAdjacentHTML("beforeend", `<style>
  .steps-sheet { max-height: 92%; } .steps-list { padding: 0 8px 8px; }
  .st-turn { border-top: 1px solid var(--border-subtle); padding: 6px 8px; } .st-turn > summary { cursor: pointer; list-style: none; display: grid; gap: 2px; padding: 6px 0; min-height: 44px; }
  .st-turn > summary::-webkit-details-marker, .st-step > summary::-webkit-details-marker { display: none; }
  .st-when { font-size: calc(12px * var(--fz, 1)); color: var(--text-secondary); } .st-bad { color: var(--status-danger); font-weight: 600; }
  .st-prompt { color: var(--text-primary); font-weight: 600; }
  .st-step > summary { cursor: pointer; list-style: none; display: flex; gap: 8px; align-items: center; padding: 6px 4px; min-height: 36px; color: var(--text-primary); }
  .st-step > summary span { flex: 1; min-width: 0; } .st-step > summary small { color: var(--text-secondary); }
  .st-step > summary:focus-visible, .st-turn > summary:focus-visible { outline: 2px solid var(--border-focus); outline-offset: -2px; }
  @media (hover: hover) { .st-step > summary:hover, .st-turn > summary:hover { background: var(--bg-subtle); } }
  .st-out { margin: 0 4px 6px 28px; padding: 8px; background: var(--bg-subtle); border-radius: var(--radius-sm, 6px); white-space: pre-wrap; word-break: break-word; font-size: calc(12px * var(--fz, 1)); }
  .st-answer { display: flex; gap: 8px; margin: 6px 4px; color: var(--text-secondary); }
</style>`);
