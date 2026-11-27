// Вкладка «Команды»: все команды из ответов всех сессий, новые сверху; хранятся на сервере. Вынесено из ядра 25.11
// (место ядра, штаб: вернуть запас 10–15 КБ). Ядро зовёт loadCommands(quiet) — обёрткой; поведение то же.
// triageNote осталась в ядре: её зовёт и экран «Выполнить» (вывод команды).
let cmdLog = null, cmdSig = "";
const KIND_HINT = { sudo: ["lock", "sudo вне разрешённого списка — выполните вручную в терминале"],
  tty: ["key", "нужен ввод (пароль) — кнопкой не выполнится, откройте в терминале"], foreign: ["monitor", "для другой машины — скопируйте и выполните там"] };
async function loadCommands(quiet) {
  const box = $("commandsView");
  if (!quiet && !cmdLog) box.innerHTML = '<div class="empty">Собираю команды из чатов…</div>';
  try { cmdLog = await api("/api/commands"); } catch (e) { if (!quiet) box.innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; return; }
  const sig = JSON.stringify(cmdLog.items.map((c) => [c.id, c.done?.at, c.done?.code, c.running, c.manual?.at]));
  if (quiet && sig === cmdSig) return;                // ничего нового — не перерисовываем (раскрытый вывод не схлопнется)
  cmdSig = sig; renderCommands();
}
// упала — команда, код и хвост вывода ушли в сессию на разбор (одну ошибку — один раз)
// Честный статус команды — только по настоящему запуску через пульт (панель или ▶️ в боте):
// выполняется · код 0 · код N · не запускалась; «сделано вручную» — отдельная пометка, карточка остаётся в списке.
const STALE = 12 * 60 * 1000;                        // дольше таймаута выполнения (10 мин) — запуск прервался
const tsMs = (t) => new Date(String(t).replace(" ", "T") + ":00Z").getTime();
function cmdState(c) {
  if (c.running) return Date.now() - tsMs(c.running) < STALE ? "running" : "lost";
  if (c.done) return c.done.code === 0 ? "ok" : "fail";
  return "new";
}
function cmdChip(c) {
  const st = cmdState(c), d = c.done;
  const chip = {
    running: `<span class="chip s-running">${ic("wait", "s16")}выполняется</span>`,
    lost: `<span class="chip bad">${ic("warn", "s16")}запуск прервался</span>`,
    ok: `<span class="chip ok">${ic("check", "s16")}код 0</span>`,
    fail: `<span class="chip bad">${ic("warn", "s16")}код ${esc(d?.code)}${d?.triage === "sent" || d?.triage === "dup" ? " · на разборе" : ""}</span>`,
    new: `<span class="chip"><span class="sdot hollow"></span>не запускалась</span>`,
  }[st];
  const manual = c.manual ? `<span class="chip accent">${ic("check", "s16")}сделано вручную</span>` : "";
  return st === "new" && manual ? manual : chip + manual;          // не запускалась, но сделана вручную — одна пометка
}
const CMD_FILTERS = [["all", "Все"], ["new", "Не запускались"], ["fail", "С ошибкой"]];
const cmdIn = (f, c) => f === "all" || (f === "new" ? cmdState(c) === "new" && !c.manual : ["fail", "lost"].includes(cmdState(c)));
function renderCommands() {
  const owner = meta?.role === "owner", all = cmdLog?.items || [];
  let f = store("cmdsFilter") || "all"; if (!CMD_FILTERS.some(([k]) => k === f)) f = "all";
  const fresh = all.filter((c) => cmdIn("new", c)).length;
  $("cmdsSeg").textContent = fresh ? `Команды · ${fresh}` : "Команды";
  const items = all.filter((c) => cmdIn(f, c));
  $("commandsView").innerHTML = `<div class="seg cmdf">${CMD_FILTERS.map(([k, label]) => {
      const n = all.filter((c) => cmdIn(k, c)).length;
      return `<button data-cf="${k}" class="${k === f ? "on" : ""}">${label}${n ? ` · ${n}` : ""}</button>`; }).join("")}</div>`
    + (items.length ? items.map((c) => {
      const st = cmdState(c), d = c.done;
      const run = c.kind === "local" && owner && st !== "running"
        ? `<button class="btn sm ${c.danger ? "danger" : ""}" data-crun="${c.id}">${c.danger ? ic("warn") : ic("play")}${d ? "Выполнить снова" : "Выполнить на " + esc(cmdLog.host)}</button>`
        : c.kind === "tty" && owner ? `<button class="btn sm ${c.danger ? "danger" : ""}" data-cterm="${c.id}">${ic("term")}Открыть в терминале</button>` : "";
      const hint = c.kind !== "local" && !d ? `<div class="hint">${ic(KIND_HINT[c.kind][0], "s16")}${KIND_HINT[c.kind][1]}</div>` : "";
      const out = d ? `<div class="result ${d.code === 0 ? "ok" : "bad"}"><div style="width:100%">${d.code === 0 ? "Готово" : "Ошибка"} · код ${esc(d.code)} · ${d.seconds} с · ${esc(localTs(d.at))}${d.by === "bot" ? " · кнопкой в боте" : ""}${d.cut ? " · показан конец вывода" : ""}
          ${d.out ? `<pre class="out">${esc(d.out)}</pre><button class="btn sm ghost cpout" data-cout="${c.id}">${ic("copy")}Копировать вывод${d.cut ? " целиком" : ""}</button>` : " · вывода нет"}</div></div>${triageNote(d.triage, d.triage_to)}`
        : st === "running" ? `<div class="result wait">${ic("wait")}<span>Выполняется с ${esc(localTs(c.running).slice(11))}…</span></div>` : "";
      return `<div class="cmd st-${st}" data-cid="${c.id}">
        <div class="meta"><b>${esc(c.win)}</b><span>· ${esc(localTs(c.ts))}</span><span class="chips">${cmdChip(c)}</span></div>
        ${c.about ? `<div class="why">${esc(c.about)}</div>` : ""}
        <pre>${esc(c.cmd)}</pre>${hint}
        <div class="acts">${run}<button class="btn sm ghost" data-ccopy="${c.id}">${ic("copy")}Копировать</button>${owner
          ? `<button class="btn sm ghost" data-cmark="${c.id}" data-done="${c.manual ? 0 : 1}">${c.manual ? "Снять пометку «вручную»" : ic("check") + "Отметить: сделано вручную"}</button>` : ""}</div>
        <div class="out-wrap">${out}</div></div>`;
    }).join("") : `<div class="empty">${!all.length ? "Команд пока нет — здесь появятся блоки кода из ответов всех сессий."
      : f === "new" ? "Все команды запускались или отмечены вручную." : "Команд с ошибкой нет."}</div>`);
}
$("commandsView").addEventListener("click", async (e) => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.cf) { store("cmdsFilter", b.dataset.cf); return renderCommands(); }
  const c = cmdLog?.items.find((x) => x.id === (b.dataset.crun || b.dataset.ccopy || b.dataset.cmark || b.dataset.cout || b.dataset.cterm)); if (!c) return;
  if (b.dataset.cterm) return termOpen(b, "/api/commands/term", { id: c.id }, c.cmd);
  if (b.dataset.cout) {                               // весь вывод — с сервера (в списке только хвост)
    if (!c.done.cut) return copyText(c.done.out, "Вывод скопирован");
    // полный вывод едет с сервера — копирование начинается сразу в нажатии (буфер, 25.11); нет полного — конец вывода
    return copyText(api("/api/commands/output?id=" + c.id).then((d) => d.out, () => c.done.out), "Вывод скопирован");
  }
  const put = (item) => { Object.assign(c, item); cmdSig = ""; renderCommands(); };
  if (b.dataset.ccopy) {
    return copyText(c.cmd, "Команда скопирована");
  }
  if (b.dataset.cmark) return busy(b, "…", async () => {
    try { put((await api("/api/commands/mark", { id: c.id, done: b.dataset.done === "1" })).item); } catch (err) { toast(err.message, 4000); }
  });
  const go = (confirmed) => busy(b, "Выполняю…", async () => {
    const card = b.closest(".cmd");
    try {
      c.running = new Date().toISOString().slice(0, 16).replace("T", " ");    // сразу «выполняется» — не ждём ответа
      card.querySelector(".chips").innerHTML = cmdChip(c);
      const r = await api("/api/commands/run", { id: c.id, confirmed });
      if (r.confirm) { c.running = null; card.querySelector(".chips").innerHTML = cmdChip(c); return ask(); }
      put(r.item); haptic("notificationOccurred", r.item.done.code === 0 ? "success" : "error");
    } catch (err) {
      c.running = null; card.querySelector(".chips").innerHTML = cmdChip(c);
      card.querySelector(".out-wrap").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`;
    }
  });
  const ask = () => confirmDanger("Команда меняет или удаляет данные:\n\n" + c.cmd.slice(0, 600) + "\n\nВыполнить?", () => go(true));
  c.danger ? ask() : go(false);
});

export { loadCommands };
