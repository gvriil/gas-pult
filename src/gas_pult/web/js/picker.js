// Модель и усилие — один выбор (владелец 19.11: «как открываются усилия списочком, так и в этом же списочке слева
// должны открываться модели; и не только в начале, а и в процессе, когда сессия уже завелась»). Слева — модели,
// справа — усилия выбранной модели (у Haiku и моделей со своим ключом поставщика усилий нет — колонка серая).
// Касание модели меняет правую колонку; выбор усилия применяет и закрывает. На телефоне — модели сверху, усилия
// снизу в одной шторке. Один компонент — в «Новом чате» (черновик) и в открытом чате: смена в процессе — один
// перезапуск с --model и --effort (тот же разговор, --resume), а только усилие — без перезапуска, «Экран» не
// открывается.

const EFFORT = [["auto", "Авто", "Claude сам решает"], ["low", "Низкие", "быстро и дёшево"], ["medium", "Средние", "обычные задачи"],
  ["high", "Высокие", "сложные задачи"], ["xhigh", "Очень высокие", "архитектура, сложный разбор"], ["max", "Максимальные", "дольше и дороже всего"]];
const SUB = { opus: "самая сильная", sonnet: "баланс скорости и качества", haiku: "самая быстрая" };
// Усилие — у Claude Code с подпиской или ключом Anthropic, и у Haiku тоже (владелец 20.11; проверено: claude -p
// --model haiku --effort low отвечает без ошибки, строка статуса Haiku показывает уровень). Другим поставщикам — нет.
const hasEffort = (profile) => (profile || "claude") === "claude";
// Модель чата, если её не выбирали вручную (model_own пуст): «Haiku 5.5» из строки статуса → алиас окна выбора
const aliasOf = (name, list) => { const n = String(name || "").toLowerCase(); if (!n) return "";
  return (list.find((m) => n === String(m.name).toLowerCase()) || list.find((m) => n.includes(m.alias)))?.alias || ""; };

// [{alias, name, sub}] — модели поставщика чата
function models(profile) {
  const p = profileOf(profile || "claude");
  if (p && p.needs_key) return [[p.main || p.default_main, "основная", "opus"], [p.fast || p.default_fast, "быстрая — рутина и субагенты", "haiku"]]
    .map(([name, sub, alias]) => ({ alias, name, sub }));
  return (meta.models || []).map((m) => ({ alias: m, name: m, sub: SUB[m] || "" }));
}

// s — открытый чат; без s — черновик «Нового чата» (DRAFT)
export function open(s) {
  const profile = s ? s.profile || "claude" : DRAFT?.profile || projOf(DRAFT?.proj)?.profile || "claude";
  const list = models(profile);
  let sel = (s ? s.model_own || aliasOf(s.model, list) : DRAFT?.model) || list[0]?.alias || "";   // модель чата, а не умолчание
  const cur = { model: sel, effort: (s ? s.effort : DRAFT?.effort) || "" };
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.model");
  bg.innerHTML = `<div class="sheet mpick" role="dialog" aria-label="Модель и усилие"><h3>Модель и усилие${s ? " · только этот чат" : ""}</h3>
    <div class="mp-cols"><div class="mp-col" id="mpModels" role="radiogroup" aria-label="Модель"></div><div class="mp-col" id="mpEff" role="radiogroup" aria-label="Усилие"></div></div>
    ${meta.role === "owner" || !s ? '<button class="mp-other" type="button" id="mpOther">' + ic("swap") + "<span>Другой поставщик или агент…</span></button>" : ""}
    <button class="cancel" data-close>Закрыть</button></div>`;
  document.body.append(bg);
  const close = () => bg.remove();
  const draw = () => {
    bg.querySelector("#mpModels").innerHTML = list.map((m) => `<button type="button" role="radio" aria-checked="${m.alias === sel}" class="mp-it${m.alias === sel ? " on" : ""}" data-m="${esc(m.alias)}">${ic("chip")}<span><b>${esc(m.name)}</b><small>${esc(m.sub)}</small></span></button>`).join("");
    const ok = hasEffort(profile, sel);
    bg.querySelector("#mpEff").innerHTML = ok
      ? EFFORT.map(([v, label, sub]) => `<button type="button" role="radio" aria-checked="${sel === cur.model && cur.effort === v}" class="mp-it${sel === cur.model && cur.effort === v ? " on" : ""}" data-e="${v}">${ic("bolt")}<span><b>${esc(label)}</b><small>${esc(sub)}</small></span></button>`).join("")
      : `<p class="note mp-none">У этой модели усилий нет.</p><button type="button" class="btn" data-e="">Выбрать ${esc(list.find((m) => m.alias === sel)?.name || sel)}</button>`;
  };
  draw();
  bg.addEventListener("click", (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) return close();
    const m = e.target.closest("[data-m]");
    if (m) { sel = m.dataset.m; return draw(); }
    const ef = e.target.closest("[data-e]");
    if (ef) { close(); return apply(s, sel, list.find((x) => x.alias === sel)?.name || sel, ef.dataset.e || null, cur); }
    if (e.target.closest("#mpOther")) { close(); return s ? switchProfile(s) : pickProfile((pid) => { if (DRAFT) { DRAFT.profile = pid; DRAFT.model = ""; paintDraft(); } }); }
  });
  bg.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  bg.querySelector(".mp-it.on, .mp-it")?.focus();
}

async function apply(s, alias, name, effort, cur) {
  if (!s) {                                            // «Новый чат»: только запомнить — запуск при первой отправке
    if (DRAFT) { DRAFT.model = alias; DRAFT.effort = effort || ""; paintDraft(); }
    return;
  }
  const label = effort ? (EFFORT.find(([v]) => v === effort)?.[1] || effort).toLowerCase() : "";
  if (alias === cur.model && effort) {                 // та же модель — только усилие, без перезапуска
    try { await api("/api/effort", { w: s.id, level: effort }); toast("Усилия: " + label); refresh(); }
    catch (e) { toast("Не вышло: " + e.message, 4500); }
    return;
  }
  toast("Перезапускаю этот чат с " + name + "…", 6000);
  try {
    const d = await api("/api/model", { w: s.id, name: alias, ...(effort ? { effort } : {}) }); await refresh(); openSession(d.id);
    toast(`«${name}»${effort && effort !== "auto" ? " · усилия: " + label : ""} — только для этого чата`, 4500);
  } catch (e) { toast("Не вышло: " + e.message, 5000); }
}

document.head.insertAdjacentHTML("beforeend", `<style>
  .mpick { max-width: 640px; } .mp-cols { display: grid; grid-template-columns: 1fr; gap: 4px; padding: 0 8px; }
  @media (min-width: 640px) { .mpick { width: min(640px, 100%); } .mp-cols { grid-template-columns: 1fr 1fr; } .mp-col + .mp-col { border-left: 1px solid var(--border-subtle); padding-left: 6px; } }
  .mp-col { display: grid; gap: 2px; align-content: start; } .mp-col + .mp-col { border-top: 1px solid var(--border-subtle); padding-top: 6px; }
  @media (min-width: 640px) { .mp-col + .mp-col { border-top: 0; padding-top: 0; } }
  .mp-it { display: flex; align-items: center; gap: 10px; min-height: 48px; padding: 8px 10px; border: 0; border-radius: var(--radius-sm); background: none;
           color: var(--text-primary); font: inherit; text-align: left; cursor: pointer; }
  .mp-it span { display: grid; } .mp-it small { color: var(--text-secondary); font-size: calc(13px * var(--fz, 1)); }
  .mp-it .i { color: var(--text-secondary); flex: none; } .mp-it.on { background: var(--accent-soft); color: var(--accent-primary); } .mp-it.on .i { color: var(--accent-primary); }
  @media (hover: hover) { .mp-it:hover { background: var(--bg-subtle); } }
  .mp-it:focus-visible, .mp-other:focus-visible { outline: 2px solid var(--border-focus); outline-offset: -2px; }
  .mp-none { margin: 10px; color: var(--text-secondary); } .mpick .btn { margin: 0 10px 8px; }
  .mp-other { display: flex; align-items: center; gap: 10px; width: calc(100% - 16px); margin: 6px 8px 0; min-height: 44px; padding: 8px 10px; border: 0;
              border-radius: var(--radius-sm); background: none; color: var(--accent-primary); font: inherit; cursor: pointer; }
</style>`);
