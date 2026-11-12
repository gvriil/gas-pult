// ---------- команды из последнего ответа: сервер берёт их сам, браузер шлёт номер и отпечаток ----------
async function renderCmds() {                          // в место .cmds под последним ответом (renderChat)
  let slot = $("content").querySelector(".cmds");
  if (!slot) { slot = document.createElement("div"); slot.className = "cmds"; const row = $("act"); row ? row.before(slot) : $("content").append(slot); }
  const d = await api("/api/cmds?w=" + encodeURIComponent(current)).catch(() => null);
  if (!d?.cmds?.length || tab !== "chat" || !slot.isConnected) return;
  const box = slot;
  box.innerHTML = `<div class="section">Команды из ответа</div>` + d.cmds.map((c) => `<div class="cmd">
    <pre>${esc(c.cmd)}</pre>${FOCUS
      ? `<div class="hint">${ic("copy", "s16")}по фокус-ссылке команды не выполняются — скопируйте и выполните в пульте или терминале</div>`
      : c.kind === "local" && meta?.role === "owner"
      ? `<button class="btn sm ${c.danger ? "danger" : ""}" data-run="${c.i}" data-sha="${c.sha}">${c.danger ? ic("warn") : ic("play")}Выполнить на ${esc(d.host)}</button>`
      : c.kind === "tty" && meta?.role === "owner"
      ? `<div class="hint">${ic("key", "s16")}нужен ввод (пароль) — кнопкой не выполнится</div><button class="btn sm ${c.danger ? "danger" : ""}" data-term="${c.i}" data-sha="${c.sha}">${ic("term")}Открыть в терминале</button>`
      : `<div class="hint">${{ sudo: ic("lock", "s16") + "sudo вне разрешённого списка — выполните вручную в терминале",
          tty: ic("key", "s16") + "нужен ввод (пароль) — выполняет владелец в терминале панели" }[c.kind] || ic("monitor", "s16") + "команда для другой машины — скопируйте и выполните там"}</div>`}
    <div class="cmdacts"><button class="btn sm ghost" data-cpcmd>${ic("copy")}Копировать</button></div>
    <div class="out-wrap"></div></div>`).join("");
}
$("content").addEventListener("click", (e) => {
  if (e.target.closest("[data-cpcmd]")) return copyText(e.target.closest(".cmd").querySelector("pre").textContent, "Команда скопирована");
  if (e.target.closest("[data-cpout]")) return copyText(e.target.closest(".out-wrap").fullOut || "", "Вывод скопирован");
  const t = e.target.closest("[data-term]");
  if (t) return termOpen(t, "/api/run/term", { w: current, i: +t.dataset.term, sha: t.dataset.sha }, t.closest(".cmd").querySelector("pre").textContent);
  const b = e.target.closest("[data-run]"); if (!b) return;
  const cmd = b.closest(".cmd").querySelector("pre").textContent;
  const go = (confirmed) => busy(b, "Выполняю…", async () => {
    const outBox = b.closest(".cmd").querySelector(".out-wrap");
    try {
      const r = await api("/api/run", { w: current, i: +b.dataset.run, sha: b.dataset.sha, confirmed });
      if (r.confirm) return ask();
      outBox.innerHTML = `<div class="result ${r.code === 0 ? "ok" : "bad"}"><div style="width:100%">${r.code === 0 ? "Готово" : "Ошибка"} · код ${esc(r.code)} · ${r.seconds} с${r.cut ? " · показан конец вывода" : ""}
        ${r.out ? `<pre class="out">${esc(r.out)}</pre><button class="btn sm ghost cpout" data-cpout>${ic("copy")}Копировать вывод${r.cut ? " целиком" : ""}</button>` : " · вывода нет"}</div></div>${triageNote(r.triage, r.triage_to)}`;
      outBox.fullOut = r.full || r.out;
      haptic("notificationOccurred", r.code === 0 ? "success" : "error");
    } catch (err) { outBox.innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`; }
  });
  const ask = () => confirmDanger("Команда меняет или удаляет данные:\n\n" + cmd.slice(0, 600) + "\n\nВыполнить?", () => go(true));
  b.classList.contains("danger") ? ask() : go(false);
});

// ---------- вкладка «Команды»: все команды из ответов всех сессий, новые сверху; хранятся на сервере ----------
let cmdLog = null, cmdSig = "";
const KIND_HINT = { sudo: ["lock", "sudo вне разрешённого списка — выполните вручную в терминале"],
  tty: ["key", "нужен ввод (пароль) — кнопкой не выполнится, откройте в терминале"], foreign: ["monitor", "для другой машины — скопируйте и выполните там"] };
async function loadCommands(quiet) {
  const box = $("commandsView");
  if (!quiet && !cmdLog) box.innerHTML = '<div class="empty">Собираю команды из сессий…</div>';
  try { cmdLog = await api("/api/commands"); } catch (e) { if (!quiet) box.innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; return; }
  const sig = JSON.stringify(cmdLog.items.map((c) => [c.id, c.done?.at, c.done?.code, c.running, c.manual?.at]));
  if (quiet && sig === cmdSig) return;                // ничего нового — не перерисовываем (раскрытый вывод не схлопнется)
  cmdSig = sig; renderCommands();
}
// упала — команда, код и хвост вывода ушли в сессию на разбор (одну ошибку — один раз)
function triageNote(t, to) {
  const m = { sent: ["chat", `Отправлено на разбор в «${esc(to)}» — Claude предложит исправление`],
    dup: ["chat", `Эта ошибка уже отправлялась на разбор в «${esc(to)}»`],
    closed: ["warn", "Сессии этой папки уже нет — на разбор не отправлено"],
    busy: ["warn", `Claude в «${esc(to)}» ждёт ответа на вопрос — на разбор не отправлено, выполните позже`],
    error: ["warn", "На разбор отправить не удалось"] }[t];
  return m ? `<div class="hint tri">${ic(m[0], "s16")}<span>${m[1]}</span></div>` : "";
}
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
    try { return copyText((await api("/api/commands/output?id=" + c.id)).out, "Вывод скопирован"); }
    catch (err) { return copyText(c.done.out, "Скопирован конец вывода — весь уже не хранится"); }
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

// ---------- вход в MCP-сервис (ссылка на экране Claude Code) ----------
function authCard(a, name, w) {
  return `<div class="ask"><p class="q">${ic("key")}<span>Вход в ${esc(a.service)}</span></p><ol class="steps">
    <li><button class="btn sm" data-openauth="${esc(a.url)}">${ic("ext")}Открыть страницу входа</button></li>
    <li>Войдите как обычно — почтой или через Google. Это происходит на сайте сервиса, панель пароль не видит.</li>
    <li>Откроется страница, которая <b>не загружается</b> (адрес начинается с http://localhost) — так и должно быть. Скопируйте её адрес и вставьте:
      <div class="field" style="margin:8px 0 0"><textarea id="authUrl" rows="3" placeholder="http://localhost:…/callback?code=…"></textarea></div>
      <button class="btn sm" style="margin-top:8px" data-finish="${esc(name || "")}" data-w="${esc(w || current)}">Завершить вход</button><div id="authResult"></div></li></ol></div>`;
}
document.addEventListener("click", async (e) => {
  const o = e.target.closest("[data-openauth]");
  if (o) { openUrl(o.dataset.openauth); return; }
  const f = e.target.closest("[data-finish]"); if (!f) return;
  const url = $("authUrl").value.trim();
  if (!url) return toast("Вставьте адрес страницы после входа");
  await busy(f, "Завершаю вход…", async () => {
    try {
      const d = await api("/api/mcp/finish", { w: f.dataset.w, url, name: f.dataset.finish || guessName() });
      const ok = d.result.startsWith("✔");
      $("authResult").innerHTML = `<div class="result ${ok ? "ok" : "bad"}">${ic(ok ? "check" : "warn")}<span>${esc(clean(d.result))}</span></div>`;
      haptic("notificationOccurred", ok ? "success" : "error");
    } catch (err) { $("authResult").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`; }
  });
});
const guessName = () => (document.querySelector(".ask .q span")?.textContent || "").replace("Вход в ", "").trim();

// ---------- «Нужен вход» (logins.py): шторка прямо в панели — только владельцу ----------
// Сервер отдаёт login в /api/screen и /api/tty только владельцу (не фокус, не пространство) и только при паре «ссылка +
// слово входа». Шторка — один раз на окно и ссылку: закрыли — не навязываем, пока ссылка та же. Код входа — только в
// окно (/api/login/code), в журналы и в адрес запроса не попадает.
const LOGIN = { seen: new Set(), open: null };
const LOGIN_KIND = { claude: "Claude", gh: "GitHub", mcp: "сервис", device: "сервис", url: "сервис" };
function loginNotice(l, w) {
  if (!l || !w || meta?.role !== "owner" || FOCUS || DEMO && !params.has("login")) return;
  const key = w + " " + l.url;
  if (LOGIN.seen.has(key) || document.querySelector(".sheet-bg.login-bg")) return;
  LOGIN.seen.add(key); loginSheet(l, w);
}
function loginSheet(l, w) {
  const name = sessions.find((x) => x.id === w)?.name || w, who = l.service || LOGIN_KIND[l.kind] || "сервис";
  const host = (() => { try { return new URL(l.url).host; } catch (e) { return ""; } })();
  const asks = l.wants === "url" ? { ph: "http://localhost:…/callback?code=…", t: "Страница после входа не загрузится — так и должно быть. Скопируйте её адрес и вставьте:" }
    : l.wants === "code" || l.kind === "claude" ? { ph: "Код со страницы входа", t: "Сайт покажет код — скопируйте его и вставьте сюда:" } : null;
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.classList.add("login-bg"); bg.dataset.help = hv("sheet.login");
  bg.innerHTML = `<div class="sheet" role="dialog" aria-labelledby="loginH"><h3 id="loginH">Нужен вход: ${esc(who)}</h3>
    <p class="note" style="margin:0 16px 8px">Окно «${esc(name)}» просит войти. Пароль вводится на сайте ${esc(host || "сервиса")} — панель его не видит.</p>
    <ol class="login-steps">
      ${l.code ? `<li><p class="lt">Код для страницы входа:</p><div class="login-code"><code id="loginOtp">${esc(l.code)}</code><button class="btn sm ghost" type="button" data-la="copy">${ic("copy")}Копировать</button></div></li>` : ""}
      <li><p class="lt">${l.code ? "Откройте страницу и введите этот код:" : "Откройте страницу входа и войдите как обычно:"}</p>
        <button class="btn sm ghost" type="button" data-la="open">${ic("ext")}Открыть ссылку</button><div class="login-url">${esc(l.url)}</div></li>
      ${asks ? `<li><p class="lt">${esc(asks.t)}</p><div class="login-in"><input id="loginIn" type="text" autocomplete="one-time-code" spellcheck="false" maxlength="512" placeholder="${esc(asks.ph)}" aria-label="${esc(asks.ph)}">
        <button class="btn sm ghost" type="button" data-la="send">${ic("send")}В окно</button></div></li>` : ""}
      <li><p class="lt">Вошли — проверим, что окно больше не ждёт:</p><button class="btn sm ghost" type="button" data-la="check">${ic("check")}Готово — проверить</button><div id="loginRes"></div></li>
    </ol>
    <button class="cancel" data-close>Закрыть</button></div>`;
  document.body.append(bg);
  const res = (ok, text) => { bg.querySelector("#loginRes").innerHTML = `<div class="result ${ok ? "ok" : "bad"}">${ic(ok ? "check" : "warn")}<span>${esc(text)}</span></div>`; };
  bg.addEventListener("click", async (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) return bg.remove();
    const b = e.target.closest("[data-la]"); if (!b) return;
    if (b.dataset.la === "copy") return copyText(l.code, "Код скопирован");
    if (b.dataset.la === "open") return openUrl(l.url);
    if (b.dataset.la === "send") {
      const inp = bg.querySelector("#loginIn"), code = inp.value.trim();
      if (!code) { inp.focus(); return toast(l.wants === "url" ? "Вставьте адрес страницы после входа" : "Вставьте код со страницы входа"); }
      if (/[\u0000-\u001f\u007f]/.test(code) || code.length > 512) return toast("Нужна одна строка до 512 знаков");
      return busy(b, "Отправляю…", async () => {
        try { await api("/api/login/code", { w, code }); inp.value = ""; toast("Отправлено в окно"); } catch (err) { res(false, err.message); }
      });
    }
    if (b.dataset.la === "check") return busy(b, "Проверяю…", async () => {
      try {
        const d = await api("/api/login/check", { w, kind: l.kind });
        res(d.ok, d.text); haptic("notificationOccurred", d.ok ? "success" : "error");
        if (d.ok) setTimeout(() => bg.remove(), 1500);
      } catch (err) { res(false, err.message); }
    });
  });
}

// ---------- вопрос Claude → у большого пальца: варианты кнопками ----------
function setAsk(html, key = html) {
  const box = $("ask");
  if (box.dataset.key !== key) { box.innerHTML = html; box.dataset.key = key; }
  padDock();
}
function renderAsk(lines, auth) {
  if (auth?.paste) { if (!$("authUrl")) setAsk(authCard(auth)); return; }
  const opts = [], re = /^\s*(❯)?\s*(\d+)\.\s+(.+?)\s*$/;
  let end = -1;
  for (let i = lines.length - 1; i >= 0; i--) {
    const m = lines[i].match(re);
    if (m) { opts.unshift({ n: m[2], text: m[3], sel: !!m[1] }); end = end < 0 ? i : end; }
    else if (opts.length) break;
  }
  // нумерованные строки с «?» бывают и вашими сообщениями — верим серверу или подсказке меню под пунктами
  const foot = end >= 0 && lines.slice(end + 1).some((l) => /Enter to (confirm|select)|Esc to (cancel|exit|go back)/.test(l));
  if (!(cur()?.status === "dialog" || foot) || opts.length < 2) return setAsk(plainOptions(lines));
  const qi = lines.findLastIndex((l, i) => i < end - opts.length + 1 && /\?\s*$/.test(l));
  const q = qi >= 0 ? lines[qi].trim() : "Claude ждёт выбора";
  // Карточку не перерисовываем, пока вопрос и пункты те же: кнопка под пальцем не подменяется до «click» (iPhone).
  const key = q + "\n" + opts.map((o) => o.n + o.text).join("\n");
  setAsk(`<div class="ask"><p class="q">${ic("warn")}<span>${esc(q)}</span></p>${opts.map((o) =>
    `<button class="opt" data-n="${o.n}"><b>${o.n}</b><span>${esc(o.text)}</span></button>`).join("")}
    <p class="tip">Коснитесь пункта — выделится, ещё раз — выбрать</p></div>`, key);
  if (Date.now() - askTap.t > 1500) markAsk(opts.find((o) => o.sel)?.n);   // свежий тап — его выделение не сбиваем
}
function markAsk(n) { document.querySelectorAll("#ask button[data-n]").forEach((b) => b.classList.toggle("sel", b.dataset.n === n)); }
// Касание — выделить пункт (стрелками до ❯), второе касание того же пункта или выделенного — выбрать (стрелки и Enter).
// Цифрой не выбираем: не всякое меню Claude Code её принимает.
const askTap = { n: "", t: 0 };
$("ask").onclick = (e) => {
  const b = e.target.closest("button[data-n]");
  if (b) {
    const n = b.dataset.n, go = b.classList.contains("sel") || (askTap.n === n && Date.now() - askTap.t < 600);
    Object.assign(askTap, { n, t: Date.now() }); markAsk(n);
    haptic("impactOccurred", go ? "medium" : "light");
    return choose(n, go, b);
  }
  const t = e.target.closest("button[data-pick]"); if (t) pick(t.dataset.pick, t);
};
async function choose(n, go, btn) {
  const run = async () => {
    try { const d = await api("/api/select", { w: current, text: "", n, go }); renderAsk(d.lines); if (tab === "screen") renderTerm(d.lines); if (go) setTimeout(refresh, 800); }
    catch (e) { toast(/^Уже ответили/.test(e.message) ? e.message : "Не вышло: " + e.message, 4500); if (/^Уже ответили/.test(e.message)) setTimeout(refresh, 300); }
  };
  return go ? busy(btn, "Выбираю…", run) : run();
}
function plainOptions(lines) {                      // меню без номеров (доверие к папке, /mcp)
  const foot = lines.findLastIndex((l) => /to navigate|Enter to confirm|Enter to select/.test(l));
  const sel = lines.findLastIndex((l, i) => i < foot && l.includes("❯"));
  if (foot < 0 || sel < 0 || /^\s*❯\s*\d+\./.test(lines[sel])) return "";
  let a = sel, z = sel;
  while (a > 0 && lines[a - 1].trim() && /^\s{2,}/.test(lines[a - 1]) && !/[:?]\s*$/.test(lines[a - 1])) a--;
  while (z < foot - 1 && lines[z + 1].trim() && /^\s{2,}/.test(lines[z + 1]) && !/^\s*(※|https?:)/.test(lines[z + 1])) z++;
  let opts = lines.slice(a, z + 1).map((l) => ({ text: l.replace("❯", "").trim(), sel: l.includes("❯") })).filter((o) => o.text);
  if (opts.some((o) => /^[✔✘⚠]/.test(o.text))) opts = opts.filter((o) => /^[✔✘⚠]/.test(o.text));
  if (opts.length < 2) return "";
  const q = lines.slice(Math.max(0, a - 6), a).reverse().find((l) => /\?\s*$/.test(l) || /^\s*\S.*(servers|MCP)/.test(l)) || "Выберите пункт";
  return `<div class="ask"><p class="q">${ic("warn")}<span>${esc(q.trim())}</span></p>${opts.map((o) =>
    `<button class="opt ${o.sel ? "sel" : ""}" data-pick="${esc(o.text.replace(/^[✔✘⚠]\s*/, "").split(/\s{2,}/)[0])}"><span>${esc(o.text.replace(/^[✔✘⚠]\s*/, ""))}</span></button>`).join("")}</div>`;
}
async function pick(text, btn) {
  await busy(btn, "Выбираю…", async () => {
    try { const d = await api("/api/select", { w: current, text }); renderAsk(d.lines); if (tab === "screen") renderTerm(d.lines); }
    catch (e) { toast(e.message, 4500); }
  });
}
$("keys").onclick = (e) => { const b = e.target.closest("button[data-key]"); if (b) press(b.dataset.key); };
async function press(key) {
  if (key === "C-c") {                              // второй Ctrl+C подряд закрывает Claude Code — не даём
    if (Date.now() - (press.cc || 0) < 3000) return toast("Ctrl+C уже отправлен. Второй подряд закроет Claude Code — подождите 3 секунды", 4000);
    press.cc = Date.now(); toast("Ctrl+C отправлен — команда прервана");
  }
  haptic("impactOccurred", "light");
  try { const d = await api("/api/key", { w: current, key }); renderAsk(d.lines); if (tab === "screen") renderTerm(d.lines); setTimeout(refresh, 800); }
  catch (e) { toast("Не вышло: " + e.message, 4000); }
}
async function act(path, body, okText) {
  try {
    const d = await api(path, { w: current, ...body });
    if (d.lines) setTab("screen");
    if (okText) toast(okText);
    haptic("impactOccurred", "light");
    return d;
  } catch (e) { toast("Не вышло: " + e.message, 4500); }
}
