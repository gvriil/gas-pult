// Фразы-подсказки под последним ответом (отзыв тестировщика 22.11 по фокус-чату: «классные фразы он набрасывает —
// только я не поняла, как их использовать? „Сколько дублей нашлось“ — как её применить?»). Агент пишет в ответе
// «Можно спросить: — «Сколько дублей нашлось?»» — панель показывает эти фразы кнопками «Можно спросить:».
// Нажатие ставит фразу в поле ввода и курсор в конец — НЕ отправляет: человек может дописать (число, имя, срок),
// случайное касание не тратит ход агента. Бейджики первого разговора (js/starters.js) — другое: это сценарии
// «нажмите — я расспрошу и сделаю», они отправляются сразу и так и подписаны.
// Подсказка «Нажмите фразу — она встанет в поле, отправьте» — пока человек не воспользовался фразой ни разу.

const MAX = 4, LEN = 140;
// Вводная строка: «Можно спросить:», «Напишите, например:», «Попросите:», «Следующие вопросы:» …
const LEAD = /(спрос|напиш|скаж|попрос|фраз|вопрос|уточн|например|ask|try)/i;
const QUOTED = /^[«"“„](.{3,140}?)[»"”“][.!]?$/;
const ITEM = /^(?:[-*•–]|\d+[.)])\s+(.+)$/;

// Текст ответа (markdown как есть) → до 4 фраз. Пункт списка после вводной строки — фраза, если он в кавычках или
// это вопрос; в кавычках с «?» — и без вводной. В строке с вводной — все «…» подряд. Код в ``` — не трогаем.
export function phrases(text) {
  const out = [], add = (s) => {
    s = s.replace(/\*\*|__/g, "").trim();
    if (s.length >= 3 && s.length <= LEN && !out.includes(s)) out.push(s);
  };
  let lead = false, code = false;
  for (const raw of String(text || "").split("\n")) {
    const l = raw.trim().replace(/^>\s*/, "");
    if (l.startsWith("```")) { code = !code; continue; }
    if (code || !l) continue;
    const it = l.match(ITEM);
    if (it) {
      const s = it[1].replace(/\*\*|__/g, "").trim(), q = s.match(QUOTED);
      if (q && (lead || /\?$/.test(q[1]))) add(q[1]);
      else if (!q && lead && /\?$/.test(s) && !/[`[\]]/.test(s)) add(s);
      continue;
    }
    const bare = l.replace(/«[^«»]*»/g, "");            // вводное слово — вне кавычек («не фраза» — не вводная)
    lead = LEAD.test(bare) && /:\s*$/.test(l);
    if (LEAD.test(bare)) for (const m of l.matchAll(/«([^«»]{3,140})»/g)) add(m[1]);
  }
  return out.slice(0, MAX);
}

const tipSeen = () => !!store("nqTip");

export function paint(slot, text) {
  slot.__t = text;
  const ps = phrases(text);
  if (!ps.length) { slot.innerHTML = ""; return; }
  slot.innerHTML = `<p class="nq-h">Можно спросить:</p><div class="nq-row" role="group" aria-label="Можно спросить">${ps.map((p) =>
    `<button type="button" class="nq" data-nq="${esc(p)}" aria-label="${esc("Вставить в поле: " + p)}">${ic("edit", "s16")}<span>${esc(p)}</span></button>`).join("")}</div>`
    + (tipSeen() ? "" : `<p class="nq-tip">Нажмите фразу — она встанет в поле, отправьте.</p>`);
}

document.addEventListener("click", (e) => {
  const b = e.target.closest?.("[data-nq]"); if (!b) return;
  const inp = b.closest("#sFeed") ? $("sInput") : $("input"); if (!inp) return;
  const t = b.dataset.nq, cur = inp.value.trim();
  inp.value = cur && cur !== t ? cur + " " + t : t;               // уже начали писать — фраза дописывается, не стирает
  inp.dispatchEvent(new Event("input", { bubbles: true }));
  inp.focus();
  try { inp.setSelectionRange(inp.value.length, inp.value.length); } catch (_) { /* не текстовое поле */ }
  if (!tipSeen()) { store("nqTip", "1"); document.querySelectorAll(".nq-tip").forEach((x) => x.remove()); }
  window.haptic?.("selectionChanged");
});

// Вид — здесь, у компонента (ядро index.html не растёт): кнопка-фраза с карандашом «вставить в поле».
if (!document.getElementById("nqCss")) document.head.insertAdjacentHTML("beforeend", `<style id="nqCss">
  .nextq:empty { display: none; }
  .nextq { margin: 4px 0 10px; }
  .nextq .nq-h { margin: 0 0 6px; font-size: calc(13px * var(--fz, 1)); color: var(--text-secondary); font-weight: 600; }
  .nextq .nq-row { display: flex; flex-wrap: wrap; gap: 8px; }
  .nextq .nq { display: inline-flex; align-items: center; gap: 8px; max-width: 100%; min-height: 44px; padding: 8px 14px; text-align: left;
    border: 1px solid var(--border-subtle); border-radius: var(--radius-md, 8px); background: var(--bg-surface); color: var(--text-primary);
    font: inherit; font-size: calc(14px * var(--fz, 1)); cursor: pointer; }
  .nextq .nq .i { flex: none; color: var(--accent-primary); }
  .nextq .nq span { overflow-wrap: anywhere; }
  .nextq .nq:active { background: var(--bg-subtle); }
  .nextq .nq:focus-visible { outline: 2px solid var(--border-focus); outline-offset: 1px; }
  @media (hover: hover) { .nextq .nq:hover { border-color: var(--accent-primary); } }
  .nextq .nq-tip { margin: 6px 0 0; font-size: calc(12px * var(--fz, 1)); color: var(--text-secondary); }
</style>`);
