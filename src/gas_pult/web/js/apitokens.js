// «Токены для 1С и CRM» — часть по требованию (#191). Решение владельца 22.11 («API с первого дня»): 1С, CRM и
// телефония ходят в /api/v1 с токеном. Выпускает владелец пульта (свои) или человек пространства (свои).
// По умолчанию — только чтение; запись — галочкой. Токен показывается один раз — на сервере только хэш.
// «Да» на черновики, команды сервера, люди, ключи, платежи — через токен закрыты всегда (access.V1_NEVER).
// Сервер: apitokens.py; пути — /api/apitokens, /api/apitokens/new, /api/apitokens/revoke. Описание — docs/API-V1.md.

const CSS = `.apt .note { margin: 6px 16px 4px; }
.apt .apt-form { display: grid; gap: 10px; margin: 6px 16px 4px; }
.apt .apt-form input[type=text] { width: 100%; min-height: 44px; box-sizing: border-box; padding: 10px 12px; border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle); background: var(--bg-surface); color: var(--text-primary); font-size: calc(15px * var(--fz, 1)); }
.apt .apt-chk { display: flex; align-items: flex-start; gap: 10px; min-height: 44px; color: var(--text-primary); }
.apt .apt-chk input { width: 20px; height: 20px; margin-top: 2px; accent-color: var(--accent-primary); flex: none; }
.apt .apt-chk small { display: block; color: var(--text-secondary); }
.apt .apt-days { display: flex; flex-wrap: wrap; gap: 6px; }
.apt .apt-new { margin: 8px 16px; padding: 12px; border-radius: var(--radius-md); background: var(--bg-subtle); display: grid; gap: 8px; }
.apt code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: calc(13px * var(--fz, 1)); word-break: break-all; }
.apt .apt-tok { display: block; padding: 8px 10px; border-radius: var(--radius-sm); background: var(--bg-surface); user-select: all; }
.apt .apt-list { margin: 4px 16px 0; display: grid; gap: 8px; }
.apt .apt-row { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-subtle); }
.apt .apt-row > span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.apt .apt-row small { display: block; color: var(--text-secondary); }
.apt .apt-row.off { opacity: .6; }
.apt .row2 { margin: 12px 16px 0; padding: 0; }
.sheet.apt button.btn { justify-content: center; gap: 8px; min-height: 48px; margin: 0; padding: 10px 18px; border-radius: var(--radius-pill);
  background: var(--accent-primary); color: var(--on-accent); font-weight: 600; font-size: calc(15px * var(--fz, 1)); text-align: center; }
.sheet.apt button.btn .i { color: inherit; }
.sheet.apt button.btn.ghost { background: transparent; color: var(--accent-primary); border: 1px solid var(--border-subtle); }
.sheet.apt button.btn.danger { background: transparent; color: var(--status-danger); border: 1px solid var(--status-danger); }
.sheet.apt button.btn.sm { width: auto; flex: none; min-height: 40px; padding: 8px 12px; }
.sheet.apt button.btn:disabled { opacity: .45; }
.sheet.apt button.scn-opt { width: auto; min-height: 44px; padding: 8px 14px; border: 1px solid var(--border-subtle); border-radius: var(--radius-pill);
  background: var(--bg-surface); color: var(--text-primary); font-size: calc(14px * var(--fz, 1)); }
.sheet.apt button.scn-opt.on { border-color: var(--accent-primary); color: var(--accent-primary); background: var(--accent-soft); }
.apt .apt-new b { display: flex; align-items: center; gap: 6px; color: var(--status-success); }`;

let styled = false, demoToks = [];
const DAYS = [[30, "30 дней"], [90, "90 дней"], [365, "Год"], [730, "2 года"]];
const when = (t) => (t ? new Date(t * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const demoTok = () => ["gpa", "demo", "0".repeat(28)].join("_");   // демо: не настоящий токен

function frame(html) {
  if (!styled) { const s = document.createElement("style"); s.textContent = CSS; document.head.append(s); styled = true; }
  const bg = document.createElement("div"); bg.className = "sheet-bg";
  bg.innerHTML = `<div class="sheet apt" role="dialog" aria-label="Токены для 1С и CRM">${html}</div>`;
  document.body.append(bg);
  return bg;
}

async function list() {
  if (DEMO) return demoToks;
  return (await api("/api/apitokens")).tokens || [];
}

const rights = (t) => (t.write ? "чтение и запись" : "только чтение");
const state = (t) => t.state === "revoked" ? "отозван " + when(t.revoked) : t.state === "expired" ? "срок вышел " + when(t.expires)
  : (t.seen ? "был " + when(t.seen) : "ещё не использовался") + " · до " + when(t.expires);

export async function open(fresh) {
  let toks;
  try { toks = await list(); } catch (e) { return toast(e.message, 4000); }
  const o = { days: 365 };
  const base = location.origin + "/api/v1";
  const bg = frame(`<h3>Токены для 1С и CRM</h3>
    <p class="note">Токен — ключ для 1С, CRM или телефонии. По нему они читают задачи, чаты и черновики через <code>${esc(base)}</code>.
      «Да» на черновики, команды сервера, люди и ключи через токен закрыты всегда. Каждый вызов — в журнале.</p>
    ${fresh ? `<div class="apt-new" aria-live="polite"><b>${ic("check", "s16")} Токен «${esc(fresh.name)}» готов</b>
      <code class="apt-tok" id="aptTok">${esc(fresh.token)}</code>
      <span class="note" style="margin:0">Скопируйте сейчас: токен показан один раз, на сервере хранится только его отпечаток.</span>
      <button class="btn" type="button" data-copy="1">${ic("copy")}Скопировать токен</button>
      <span class="note" style="margin:0">Проверка: <code>curl -H "Authorization: Bearer …" ${esc(base)}/sessions</code></span></div>` : ""}
    <div class="section" style="margin:8px 16px 0">Новый токен</div>
    <div class="apt-form">
      <input type="text" id="aptName" maxlength="60" autocomplete="off" placeholder="Например, 1С Бухгалтерия" aria-label="Название токена" enterkeyhint="go">
      <label class="apt-chk"><input type="checkbox" id="aptWrite"><span>Запись<small>создавать задачи и писать агенту в чат. Без галочки — только чтение</small></span></label>
      <div class="apt-days" role="radiogroup" aria-label="Срок">${DAYS.map(([d, l]) => sChip(d === o.days, `data-days="${d}"`, l)).join("")}</div>
      <button class="btn wide" type="button" data-make="1">${ic("key")}Выпустить токен</button>
    </div>
    <div class="section" style="margin:12px 16px 0">Выпущенные</div>
    <div class="apt-list">${toks.length ? toks.map((t) => `<div class="apt-row${t.state === "active" ? "" : " off"}">${ic("key", "s16")}
      <span><b>${esc(t.name)}</b><small>${esc(rights(t))} · ${esc(state(t))}</small></span>
      ${t.state === "active" ? `<button class="btn danger sm" type="button" data-revoke="${esc(t.id)}">Отозвать</button>` : ""}</div>`).join("")
      : '<p class="note" style="margin:0">Пока ни одного.</p>'}</div>
    <div class="row2"><button class="btn ghost wide" type="button" data-close>Закрыть</button></div>`);
  bg.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (e.target === bg || b?.hasAttribute("data-close")) return bg.remove();
    if (!b) return;
    if (b.dataset.copy) return copyText(fresh.token, "Токен скопирован — вставьте в 1С или CRM после «Bearer »");
    if (b.dataset.days) {
      o.days = Number(b.dataset.days);
      bg.querySelectorAll("[data-days]").forEach((x) => { const on = x === b; x.classList.toggle("on", on); on ? x.setAttribute("aria-pressed", "true") : x.removeAttribute("aria-pressed"); });
      return;
    }
    if (b.dataset.revoke) {
      const t = toks.find((x) => x.id === b.dataset.revoke);
      return confirmDanger(`Отозвать «${t?.name || "токен"}»? 1С или CRM с ним перестанут получать данные сразу.`, async () => {
        try {
          if (DEMO) demoToks = demoToks.map((x) => x.id === t.id ? { ...x, state: "revoked", revoked: Date.now() / 1000 } : x);
          else await api("/api/apitokens/revoke", { id: t.id });
          toast("Отозван"); bg.remove(); open();
        } catch (er) { toast(er.message, 4000); }
      });
    }
    if (b.dataset.make) {
      const name = $("aptName").value.trim(), write = $("aptWrite").checked;
      if (!name) { $("aptName").focus(); return toast("Назовите токен — чтобы потом знать, что отзывать", 3500); }
      b.disabled = true;
      try {
        const now = Date.now() / 1000;
        const d = DEMO ? { id: "d" + Date.now(), name, write, token: demoTok(), state: "active", created: now, expires: now + o.days * 86400, seen: null }
          : await api("/api/apitokens/new", { name, write, days: o.days });
        if (DEMO) demoToks.unshift({ ...d, token: undefined });
        bg.remove(); open(d);
        copyText(d.token, "Токен выпущен и скопирован", true);
      } catch (er) { b.disabled = false; toast(er.message, 4000); }
    }
  });
  $("aptName").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); bg.querySelector("[data-make]").click(); } };
}

Object.assign(window, { apiTokens: open });
