// «Настройки» → «Платежи» (billing/, владелец 22.11: «не экономим на безопасности платежей»). Только владельцу.
// Счета и тарифы без поставщика: оплата онлайн ждёт юрлица, оплату отмечают вручную с основанием. Журнал не правится —
// аннулирование пишет встречные записи. Каждое действие несёт ключ операции: повтор (сеть, код подтверждения) не дублирует.
// Суммы считает сервер в целых центах; панель показывает готовые строки (amount_text) и ничего не складывает сама.

const ST = { draft: ["черновик", "file"], issued: ["выставлен, ждёт оплаты", "wait"], paid: ["оплачен", "check"], void: ["аннулирован", "x"] };
const PERIOD = { once: "разово", month: "в месяц", year: "в год" };
const day = (ts) => ts ? new Date(ts * 1000).toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) : "";
const newKey = () => (crypto.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2)).replace(/[^A-Za-z0-9_.:-]/g, "");
const call = (path, body) => DEMO ? demo(path, body) : api(path, body);

export async function open() {
  let p, l;
  try { [p, l] = await Promise.all([call("/api/billing/plans"), call("/api/billing/invoices")]); } catch (e) { return toast(e.message, 5000); }
  const prov = p.provider || {};
  sheet("Платежи", [
    { info: true, icon: "lock", label: prov.connected ? "Оплата онлайн подключена" : "Оплата онлайн не подключена",
      sub: prov.connected ? prov.name : (prov.note || "поставщик не подключён") + " · счета и оплату ведите вручную" },
    { label: "Новый счёт", icon: "plus", sub: "черновик: клиент, услуга, цена", run: () => invoiceForm(p) },
    ...(l.invoices.length ? [{ head: "Счета" }] : [{ info: true, icon: "file", label: "Счетов пока нет", sub: "создайте первый — сначала черновик, потом «Выставить»" }]),
    ...l.invoices.map((x) => ({ label: `${x.number} · ${x.client}`, icon: ST[x.status][1], sub: `${x.total_text} · ${ST[x.status][0]} · ${day(x.created)}`, run: () => card(x.id) })),
    { head: "Тарифы" },
    ...p.plans.map((x) => ({ info: true, icon: "coin", label: x.title, sub: `${x.amount_text} ${PERIOD[x.period] || ""} · код ${x.code}` })),
    { label: "Новый тариф", icon: "plus", sub: "цена не меняется: новая цена — новый тариф", run: () => planForm(p) },
  ]);
}

async function card(id) {
  let d; try { d = await call("/api/billing/invoice?id=" + id); } catch (e) { return toast(e.message, 5000); }
  const act = {
    issued: { label: "Выставить", icon: "send", sub: "счёт уйдёт в журнал, строки и сумма больше не меняются", run: () => step(d, "issue", {}) },
    paid: { label: "Отметить оплату вручную", icon: "check", sub: "с основанием: выписка, платёжное поручение", run: () => reasonForm(d, "pay") },
    void: { label: "Аннулировать", icon: "x", danger: true, sub: d.status === "paid" ? "встречные записи к выставлению и оплате" : "встречная запись — журнал не правится", run: () => reasonForm(d, "void") },
  };
  sheet(`${d.number} · ${ST[d.status][0]}`, [
    { info: true, icon: "place", label: d.client, sub: `${d.space ? d.space + " · " : ""}создан ${day(d.created)}${d.issued ? " · выставлен " + day(d.issued) + " · оплатить за " + d.due_days + " дн." : ""}` },
    ...d.items.map((x) => ({ info: true, icon: x.plan ? "coin" : "file", label: x.title, sub: `${x.qty} × · ${x.amount_text}` })),
    { info: true, icon: "coin", label: "Итого " + d.total_text, sub: d.status === "issued" ? "к оплате " + d.balance_text : ST[d.status][0] },
    ...d.next.map((s) => act[s]).filter(Boolean),
    { head: "Журнал" },
    ...d.journal.map((j) => ({ info: true, icon: j.op === "reversal" ? "back" : j.op === "payment" ? "check" : "lines",
      label: `${{ create: "Создан", issue: "Выставлен", payment: "Оплата", void: "Аннулирован", reversal: "Встречная запись" }[j.op] || j.op}${j.amount ? " · " + j.amount_text : ""}`,
      sub: [new Date(j.ts * 1000).toLocaleString("ru-RU"), j.reason].filter(Boolean).join(" · ") })),
  ]);
}

async function step(d, what, extra) {
  try {
    await call("/api/billing/invoice/" + what, { id: d.id, key: extra.key || newKey(), ...extra });
    toast({ issue: "Счёт выставлен", pay: "Оплата отмечена", void: "Счёт аннулирован" }[what]); card(d.id);
  } catch (e) { toast(e.message, 5000); }
}

// Форма в шторке: поля + «Отмена / Готово»; ключ операции создаётся при открытии — повторное «Готово» его не меняет
function form(title, html, note, ok, go) {
  const bg = document.createElement("div"); bg.className = "sheet-bg";
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>${esc(title)}</h3><div style="padding:4px 16px 0">${html}</div>
    ${note ? `<p class="note" style="margin:0 16px">${esc(note)}</p>` : ""}
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" data-ok>${esc(ok)}</button></div></div>`;
  document.body.append(bg);
  const key = newKey(), v = (id) => bg.querySelector("#" + id)?.value.trim() || "";
  bg.querySelector("input, textarea")?.focus();
  bg.querySelector("[data-ok]").onclick = (e) => busy(e.currentTarget, "Сохраняю…", async () => { try { if (await go(v, key) !== false) bg.remove(); } catch (er) { toast(er.message, 5000); } });
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
  bg.addEventListener("keydown", (e) => { if (e.key === "Escape") bg.remove(); });
}
const ROW = "display:grid;grid-template-columns:1fr 1.3fr 96px;gap:8px";   // количество · цена · валюта: валюта не сжимается
const field = (id, label, inner) => `<div class="field"><label for="${id}">${esc(label)}</label>${inner}</div>`;
const input = (id, label, ph = "", mode = "text") => field(id, label, `<input id="${id}" autocomplete="off" inputmode="${mode}" placeholder="${esc(ph)}">`);
const select = (id, label, opts, cur) => field(id, label, `<select id="${id}">${opts.map(([v, t]) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(t)}</option>`).join("")}</select>`);

function invoiceForm(p) {
  const cur = p.plans[0]?.currency || "EUR";
  form("Новый счёт",
    input("bClient", "Клиент", "Имя или компания") +
    (p.plans.length ? select("bPlan", "Тариф", [["", "Без тарифа — своя строка"], ...p.plans.map((x) => [x.code, `${x.title} · ${x.amount_text}`])], "") : "") +
    input("bTitle", "Услуга", "Что оплачивают") +
    `<div style="${ROW}">${input("bQty", "Количество", "1", "numeric")}${input("bPrice", "Цена за единицу", "12.50", "decimal")}${select("bCur", "Валюта", (p.currencies || ["EUR"]).map((c) => [c, c]), cur)}</div>`,
    "Черновик можно аннулировать. После «Выставить» строки и сумма не меняются.", "Создать черновик",
    async (v, key) => {
      if (!v("bClient")) return toast("Впишите клиента"), false;
      const qty = v("bQty") || "1", line = v("bPlan") ? { plan: v("bPlan"), qty } : { title: v("bTitle"), qty, price: v("bPrice").replace(",", ".") };
      if (!line.plan && (!line.title || !line.price)) return toast("Впишите услугу и цену или выберите тариф"), false;
      const d = await call("/api/billing/invoice/new", { key, client: v("bClient"), currency: v("bCur") || cur, lines: [line] });
      toast("Черновик " + d.number + " создан"); card(d.id);
    });
}

function planForm(p) {
  form("Новый тариф",
    input("tTitle", "Название", "Например: Базовый") + input("tCode", "Код (латиницей)", "basic-month") +
    `<div style="display:grid;grid-template-columns:1fr 96px;gap:8px">${input("tPrice", "Цена", "9.00", "decimal")}${select("tCur", "Валюта", (p.currencies || ["EUR"]).map((c) => [c, c]), "EUR")}</div>` +
    select("tPer", "Период", Object.entries(PERIOD), "month"),
    "Цену тарифа поменять нельзя — так счета по нему остаются честными. Новая цена — новый тариф.", "Добавить тариф",
    async (v, key) => {
      await call("/api/billing/plan", { key, code: v("tCode"), title: v("tTitle"), price: v("tPrice").replace(",", "."), currency: v("tCur"), period: v("tPer") });
      toast("Тариф добавлен"); open();
    });
}

function reasonForm(d, what) {
  const pay = what === "pay";
  form(pay ? "Оплата " + d.number : "Аннулировать " + d.number,
    field("rWhy", pay ? "Основание оплаты" : "Причина", `<textarea id="rWhy" rows="3" placeholder="${pay ? "Выписка банка от …, платёжное поручение №…" : "Почему счёт больше не нужен"}"></textarea>`) +
    (pay ? input("rRef", "Номер документа (необязательно)", "") : ""),
    pay ? `Сумма ${d.total_text}. Запись в журнале не меняется и не удаляется.` : "Журнал не правится: к выставлению и оплате добавятся встречные записи.",
    pay ? "Отметить оплату" : "Аннулировать",
    async (v, key) => {
      if (!v("rWhy")) return toast(pay ? "Впишите основание" : "Впишите причину"), false;
      await step(d, what, { key, reason: v("rWhy"), ...(pay && v("rRef") ? { ref: v("rRef") } : {}) });
    });
}

// Демо (?demo): вымышленные тарифы и счета в памяти страницы; сервер не трогается
let D;
function demo(path, b) {
  const t = Math.floor(Date.now() / 1000), fmt = (n) => (n < 0 ? "-" : "") + Math.floor(Math.abs(n) / 100) + "." + String(Math.abs(n) % 100).padStart(2, "0") + " EUR";
  const cents = (s) => { const [a, f = ""] = String(s || "0").split("."); return (+a || 0) * 100 + (+(f + "00").slice(0, 2) || 0); };   // демо: тоже без float
  D ||= { n: 2, plans: [{ code: "demo-start", title: "Пример: Старт", amount: 900, currency: "EUR", period: "month" }, { code: "demo-team", title: "Пример: Команда", amount: 2900, currency: "EUR", period: "month" }],
    inv: [{ id: 2, number: "GP-2026-00002", client: "Лавка «Пример»", space: "", currency: "EUR", status: "issued", created: t - 3 * 86400, issued: t - 2 * 86400, due_days: 14, items: [{ title: "Пример: Команда", plan: "demo-team", qty: 1, unit: 2900, amount: 2900 }],
      journal: [{ seq: 3, ts: t - 3 * 86400, op: "create", amount: 0, reason: "" }, { seq: 4, ts: t - 2 * 86400, op: "issue", amount: 2900, reason: "" }] },
    { id: 1, number: "GP-2026-00001", client: "Мастерская «Образец»", space: "", currency: "EUR", status: "paid", created: t - 9 * 86400, issued: t - 9 * 86400, paid: t - 5 * 86400, due_days: 14, items: [{ title: "Пример: Старт", plan: "demo-start", qty: 1, unit: 900, amount: 900 }],
      journal: [{ seq: 1, ts: t - 9 * 86400, op: "issue", amount: 900, reason: "" }, { seq: 2, ts: t - 5 * 86400, op: "payment", amount: 900, reason: "выписка банка (пример)" }] }] };
  const view = (x) => { const total = x.items.reduce((s, i) => s + i.amount, 0); return { ...x, total, total_text: fmt(total), balance: x.status === "issued" ? total : 0, balance_text: fmt(x.status === "issued" ? total : 0),
    items: x.items.map((i) => ({ ...i, amount_text: fmt(i.amount) })), journal: x.journal.map((j) => ({ ...j, amount_text: fmt(j.amount) })),
    next: { draft: ["issued", "void"], issued: ["paid", "void"], paid: ["void"], void: [] }[x.status] }; };
  const P = Promise.resolve.bind(Promise), find = (id) => D.inv.find((x) => x.id === +id);
  if (path === "/api/billing/plans") return P({ plans: D.plans.map((x) => ({ ...x, amount_text: fmt(x.amount) })), provider: { name: "none", connected: false, note: "поставщик не подключён — ждёт юрлица" }, currencies: ["EUR", "USD"] });
  if (path === "/api/billing/invoices") return P({ invoices: D.inv.map(view) });
  if (path.startsWith("/api/billing/invoice?")) return P(view(find(path.split("id=")[1])));
  const x = find(b?.id), log = (op, amount, reason = "") => x.journal.push({ seq: Date.now(), ts: t, op, amount, reason });
  if (path === "/api/billing/invoice/new") {
    const pl = D.plans.find((y) => y.code === b.lines[0].plan), unit = pl ? pl.amount : cents(b.lines[0].price), qty = +b.lines[0].qty || 1;
    const inv = { id: ++D.n, number: "GP-2026-0000" + D.n, client: b.client, space: "", currency: "EUR", status: "draft", created: t, due_days: 14, items: [{ title: pl?.title || b.lines[0].title, plan: pl?.code || null, qty, unit, amount: unit * qty }], journal: [{ seq: t, ts: t, op: "create", amount: 0, reason: "" }] };
    D.inv.unshift(inv); return P(view(inv));
  }
  if (path === "/api/billing/plan") { D.plans.push({ code: b.code, title: b.title, amount: cents(b.price), currency: "EUR", period: b.period }); return P({}); }
  if (path.endsWith("/issue")) { x.status = "issued"; x.issued = t; log("issue", view(x).total); }
  if (path.endsWith("/pay")) { x.status = "paid"; x.paid = t; log("payment", view(x).total, b.reason); }
  if (path.endsWith("/void")) { log("void", 0, b.reason); for (const j of x.journal.filter((j) => ["issue", "payment"].includes(j.op))) log("reversal", -j.amount, b.reason); x.status = "void"; }
  return P(view(x));
}
