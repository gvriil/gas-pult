// Расход по ценам API (владелец 22.11: «строки 💰 в каждом чате не нужны»): один экран — только владельцу. Период
// «Сегодня / Вчера / 7 дней», сумма крупно, столбики по часам (за 7 дней — по дням) и проекты по убыванию.
// Данные — GET /api/spend (spend.py читает очередь оповещений, ничего не пересчитывает). Без библиотек: столбики —
// div, цвета — токены из начала <style>. «Сегодня» крупно — r.live (22.11): то же число, что в меню и на главной
// (todayText в ядре, usage.py); почасовая сводка отстаёт до часа — её сумма подписана отдельно, под столбиками.

const CSS = `.spend .sseg { display: flex; max-width: none; gap: 4px; margin: 4px 16px 0; padding: 3px; background: var(--bg-subtle); border-radius: var(--radius-sm); }
.spend .sseg button { flex: 1; min-height: 36px; border: 0; border-radius: 6px; background: none; color: var(--text-secondary); font: inherit; font-size: calc(14px * var(--fz, 1)); cursor: pointer; }
.spend .sseg button.on { background: var(--bg-surface); color: var(--text-primary); font-weight: 600; box-shadow: var(--shadow-sm); }
.spend .sp-sum { margin: 14px 16px 0; font-size: calc(34px * var(--fz, 1)); font-weight: 700; line-height: 1.1; color: var(--text-primary); font-variant-numeric: tabular-nums; }
.spend .sp-note { margin: 2px 16px 0; color: var(--text-muted); font-size: calc(13px * var(--fz, 1)); }
.spend .sp-bars { display: flex; align-items: flex-end; gap: 2px; height: 96px; margin: 14px 16px 0; padding-bottom: 1px; border-bottom: 1px solid var(--border-subtle); }
.spend .sp-bars i { flex: 1; min-height: 2px; border-radius: 3px 3px 0 0; background: var(--accent-primary); }
.spend .sp-bars i.z { background: var(--border-subtle); }
.spend .sp-bars i.on { background: var(--text-primary); }
.spend .sp-ax { display: flex; justify-content: space-between; margin: 4px 16px 0; color: var(--text-muted); font-size: calc(11px * var(--fz, 1)); font-variant-numeric: tabular-nums; }
.spend .sp-ax span { flex: 1; text-align: center; }
.spend .sp-tip { min-height: 18px; margin: 6px 16px 0; color: var(--text-secondary); font-size: calc(13px * var(--fz, 1)); }
.spend ul { list-style: none; margin: 4px 0 0; padding: 0 16px; }
.spend li { position: relative; display: flex; justify-content: space-between; gap: 12px; padding: 9px 10px; margin-top: 4px; border-radius: var(--radius-sm); overflow: hidden; color: var(--text-primary); }
.spend li b { font-weight: 600; font-variant-numeric: tabular-nums; }
.spend li span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.spend li::before { content: ""; position: absolute; inset: 0 auto 0 0; width: var(--w); background: var(--accent-soft); z-index: -1; }
.spend li { isolation: isolate; }
.spend .sp-empty { margin: 12px 16px 0; color: var(--text-muted); }`;

const PERIODS = [["today", "Сегодня"], ["yesterday", "Вчера"], ["7d", "7 дней"]];
const WD = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const money = (x) => "$" + (x >= 1000 ? Math.round(x).toLocaleString("ru-RU") : (+x || 0).toFixed(2));
const hh = (h) => String(h).padStart(2, "0") + ":00";
const day = (iso) => { const d = new Date(iso + "T12:00:00"); return `${WD[d.getDay()]} ${d.getDate()}.${String(d.getMonth() + 1).padStart(2, "0")}`; };

function bars(r) {
  const rows = r.days ? r.days.map((d) => ({ usd: d.usd, tip: day(d.date), ax: WD[new Date(d.date + "T12:00:00").getDay()] }))
    : (r.hours || []).map((h) => ({ usd: h.usd, tip: `${hh(h.h)}–${hh((h.h + 1) % 24)}`, ax: h.h % 6 === 0 ? String(h.h) : "" }));
  const max = Math.max(...rows.map((x) => x.usd), 0);
  const html = rows.map((x, i) => `<i data-b="${i}" class="${x.usd ? "" : "z"}" style="height:${max ? Math.max(2, Math.round(x.usd / max * 100)) : 2}%" title="${esc(x.tip)} · ${money(x.usd)}"></i>`).join("");
  const ax = rows.map((x) => `<span>${x.ax}</span>`).join("");
  return { rows, html: `<div class="sp-bars" role="img" aria-label="${r.days ? "Расход по дням" : "Расход по часам"}">${html}</div><div class="sp-ax">${ax}</div>` };
}

export function open(period = "today") {
  if (!document.getElementById("spendCss")) document.head.insertAdjacentHTML("beforeend", `<style id="spendCss">${CSS}</style>`);
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = "sheet.spend";
  bg.innerHTML = `<div class="sheet spend" role="dialog" aria-labelledby="spTitle"><h3 id="spTitle">Расход по ценам API</h3>
    <div class="sseg" role="radiogroup" aria-label="Период">${PERIODS.map(([v, l]) => `<button type="button" role="radio" data-p="${v}">${l}</button>`).join("")}</div>
    <div id="spBody" aria-live="polite"><p class="sp-empty">Загружаю…</p></div>
    <button class="cancel" data-close>Закрыть</button></div>`;
  document.body.append(bg);
  const $s = (s) => bg.querySelector(s);
  let seq = 0;
  async function load(p) {
    bg.querySelectorAll("[data-p]").forEach((b) => { b.classList.toggle("on", b.dataset.p === p); b.setAttribute("aria-checked", b.dataset.p === p); });
    const n = ++seq;
    let r;
    try { r = await api("/api/spend?period=" + p); } catch (e) { if (n === seq) $s("#spBody").innerHTML = `<p class="sp-empty">${esc(e.message)}</p>`; return; }
    if (n !== seq) return;
    const live = p === "today" && r.live ? r.live : null;   // одно число «сегодня» — как в меню и на главной
    const b = bars(r), top = r.projects?.[0]?.usd || 0;
    const upd = r.updated ? new Date(r.updated * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
    const span = p === "7d" ? `${day(r.from)} — ${day(r.to)}` : day(r.from);
    const hourly = live ? `<p class="sp-note">По часам — сводка раз в час${upd ? ", обновлено " + esc(upd) : ""}: ${money(r.total)}</p>` : "";
    $s("#spBody").innerHTML = `<div class="sp-sum" data-spend-sum>${live ? (live.usd == null ? "цена ?" : usd(live.usd)) : money(r.total)}</div>
      <p class="sp-note">${live ? esc("Сегодня" + estTag(live) + " · " + COST_WHAT) : esc(span) + (upd ? " · обновлено " + esc(upd) : "")}</p>
      ${hourly}${b.html}<p class="sp-tip" id="spTip">${r.days ? "Нажмите столбик — сумма за день" : "Нажмите столбик — сумма за час"}</p>
      <h3>Проекты и окна</h3>
      ${r.projects?.length ? `<ul>${r.projects.map((x) => `<li style="--w:${top ? Math.round(x.usd / top * 100) : 0}%"><span>${esc(x.name)}</span><b>${money(x.usd)}</b></li>`).join("")}</ul>`
        : `<p class="sp-empty">${r.updated ? "За этот период расхода нет" : "Данных пока нет: сводка приходит раз в час"}</p>`}
      <p class="sp-note" style="margin:12px 16px 4px">По ценам API Anthropic: с подпиской это оценка, а не счёт. Сводку считают раз в час.</p>`;
    $s(".sp-bars").addEventListener("click", (e) => {
      const i = e.target.closest("[data-b]"); if (!i) return;
      bg.querySelectorAll(".sp-bars i.on").forEach((x) => x.classList.remove("on")); i.classList.add("on");
      const x = b.rows[+i.dataset.b]; $s("#spTip").textContent = `${x.tip} · ${money(x.usd)}`;
    });
  }
  bg.addEventListener("click", (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) return bg.remove();
    const p = e.target.closest("[data-p]"); if (p) load(p.dataset.p);
  });
  load(period);
}
