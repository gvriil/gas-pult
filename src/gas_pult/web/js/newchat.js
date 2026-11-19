// Новый чат (владелец 19.11: «новая сессия по сути — это новый чат… вместо „новой сессии“ должно быть просто поле для
// ввода текста и выбора каких-то настроек; мне очень нравится, как у Claude это сделано»). Одно поле, под ним —
// бейджики-сценарии; в поле — строка настроек: папка (проект), модель или другой агент, усилие, интеграции. Значения
// по умолчанию — последние использованные; обязательного нет. Первая отправка создаёт чат и отправляет сообщение —
// без отдельного шага «создать сессию». Название чат получит по смыслу (projects.title_of, js/nametip.js).

const EFFORT = [["", "Обычные", "как настроено"], ["auto", "Авто", "Claude сам решает"], ["low", "Низкие", "быстро и дёшево"], ["medium", "Средние", "обычные задачи"],
  ["high", "Высокие", "сложные задачи"], ["xhigh", "Очень высокие", "архитектура, сложный разбор"], ["max", "Максимальные", "дольше и дороже всего"]];
let MCP = null;                                         // подключённые интеграции — один раз за показ
const lastOff = () => { try { return JSON.parse(store("lastMcpOff") || "[]"); } catch (e) { return []; } };

const agents = () => meta?.agents || [];
const choices = () => readyProfiles().length + agents().length;
const profTitle = (id) => agents().find((a) => a.id === id)?.title || profileOf(id || "claude")?.title || "Claude";
const okProfile = (id) => !id || agents().some((a) => a.id === id) || readyProfiles().some((p) => p.id === id);
const chip = (attr, icon, text, title, on) => `<button class="dchip${on ? " on" : ""}" type="button" ${attr} title="${esc(title)}">${ic(icon)}<span>${esc(text)}</span>${ic("chev", "s16")}</button>`;

export function paint() {
  if (!DRAFT) return;
  DRAFT.mcpOff ??= lastOff();                          // интеграции, выключенные для нового чата (по умолчанию — как в прошлый раз)
  if (!okProfile(DRAFT.profile)) DRAFT.profile = "";    // прежний выбор больше недоступен — по умолчанию проекта
  const p = projOf(DRAFT.proj), prof = DRAFT.profile || p?.profile || "claude", claude = !agents().some((a) => a.id === prof) && prof === "claude";
  $("title").textContent = "Новый чат"; $("title").classList.remove("sw");
  setSub(`<span>${esc([p?.name, profTitle(prof)].filter(Boolean).join(" · "))}</span>`);
  if ($("draftNote")) $("draftNote").textContent = "Напишите, что нужно, — чат начнётся с первого сообщения. Настройки — в поле ввода, их можно не трогать.";
  const eff = EFFORT.find(([v]) => v === (DRAFT.effort || "")) || EFFORT[0];
  $("draftBar").innerHTML = (p ? chip("data-dfold", "folder", p.name, "Проект: куда положить чат") : "")
    + (DRAFT.route ? `<button class="dchip${DRAFT.model ? " on" : ""}" type="button" data-droute aria-pressed="${!!DRAFT.model}" title="${esc("Почему: " + DRAFT.route.why)}">${ic(DRAFT.model ? "check" : "spark")}<span>${esc((DRAFT.model ? "" : "Подходит: ") + DRAFT.route.label)}</span></button>` : "")
    + chip("data-dmodel", "chip", (DRAFT.model || profTitle(prof)) + (claude && !/haiku/i.test(DRAFT.model || "") ? " · усилия: " + eff[1].toLowerCase() : ""),
      "Модель и усилие — один выбор", !!(DRAFT.model || DRAFT.effort))
    + (MCP?.length ? chip("data-dmcp", "puzzle", "Интеграции: " + onCount(DRAFT.mcpOff) + (DRAFT.mcpOff.length ? " из " + okCount() : ""),
      claude ? "Какие интеграции доступны этому чату" : "У другого агента интеграции — в его настройках", DRAFT.mcpOff.length > 0) : "");
  $("input").placeholder = "Напишите, что нужно…";
  if (MCP === null) { MCP = []; api("/api/mcp").then((d) => { MCP = d.servers || []; if (DRAFT) paint(); }).catch(() => {}); }
}

const okCount = () => (MCP || []).filter((x) => x.ok).length;
const onCount = (off) => (MCP || []).filter((x) => x.ok && !off.includes(x.name)).length;
const isClaude = () => { const prof = DRAFT?.profile || projOf(DRAFT?.proj)?.profile || "claude"; return prof === "claude" || !agents().some((a) => a.id === prof); };
// Переключатели: нажатие — включить или выключить для этого чата, меню остаётся открытым (после действия — на месте)
function mcpMenu(anchor) {
  const claude = isClaude();
  popMenu(anchor, [...MCP.map((x) => {
    const on = x.ok && !DRAFT.mcpOff.includes(x.name);
    return { icon: !x.ok ? "warn" : on ? "check" : "x", on, label: x.name,
      sub: !x.ok ? "не отвечает" : !claude ? "у другого агента — в его настройках" : on ? "включена — нажмите, чтобы выключить в этом чате" : "выключена в этом чате — нажмите, чтобы включить",
      run: () => { if (x.ok && claude) { DRAFT.mcpOff = on ? [...DRAFT.mcpOff, x.name] : DRAFT.mcpOff.filter((n) => n !== x.name); paint(); } mcpMenu($("draftBar").querySelector("[data-dmcp]") || anchor); } };
  }), { sep: true }, { label: "Подключить новую или настроить…", icon: "puzzle", run: () => setHome("integrations") }]);
}

$("draftBar").onclick = (e) => {
  if (!DRAFT) return;
  const f = e.target.closest("[data-dfold]"), m = e.target.closest("[data-dmodel]"), r = e.target.closest("[data-droute]");
  const mc = e.target.closest("[data-dmcp]");
  const back = () => { paint(); $("input").focus(); };
  if (r && DRAFT.route) {                              // роутер (router.py): подсказка — нажал, чат запустится с этой моделью
    const on = !DRAFT.model; Object.assign(DRAFT, on ? { profile: DRAFT.route.profile, model: DRAFT.route.model } : { profile: "", model: "" });
    return back();
  }
  if (f) return popMenu(f, [...(projData?.projects || []).filter((p) => !p.archived).map((p) => ({ label: p.name, icon: "folder", on: p.id === DRAFT.proj, run: () => { DRAFT.proj = p.id; back(); } })),
    { sep: true }, { label: "Новая папка…", icon: "plus", run: () => newFolder() }]);
  if (m) return part("picker").then((x) => x.open());                 // модель и усилие — одно окно (js/picker.js)
  if (mc) return mcpMenu(mc);
};

let routeT = 0;                                         // подсказка модели по первому сообщению — после паузы в наборе
$("input").addEventListener("input", () => {
  if (!DRAFT) return;
  clearTimeout(routeT);
  routeT = setTimeout(async () => {
    const text = $("input").value.trim(); if (!DRAFT || text.length < 12) return;
    try { const r = (await api("/api/route", { text })).route; if (DRAFT && !DRAFT.model && r?.type !== DRAFT.route?.type) { DRAFT.route = r; paint(); } } catch (e) { /* без подсказки */ }
  }, 700);
});

export async function send() {
  const text = $("input").value.trim();
  if (!text && !files.length) return toast("Напишите первое сообщение");
  if (files.some((f) => !f.path)) { toast("Дождусь загрузки файла и начну чат", 2500); await Promise.all(files.map((f) => f.done)); }
  const dr = DRAFT, p = projOf(dr.proj), keep = files;
  $("send").disabled = true;
  toast(p ? "Начинаю чат в «" + p.name + "»…" : "Начинаю чат…", 4000);
  try {
    const off = isClaude() ? (dr.mcpOff || []) : [];
    const d = p ? await api("/api/project/session", { id: dr.proj, profile: dr.profile, model: dr.model || "", mcp_off: off, effort: dr.effort || "" })
      : await api("/api/new", { name: "", effort: dr.effort || "" });   // пространство: своя папка, усилие — при запуске
    if (p) store("lastProj", dr.proj);
    store("lastProfile", dr.model ? "" : dr.profile || ""); store("lastEffort", dr.effort || ""); store("lastMcpOff", JSON.stringify(off));
    await openSession(d.id);                          // черновик гаснет в show()
    $("input").value = text; files = keep; renderFiles(); grow();
    await sendText();
  } catch (e) { toast("Не вышло: " + e.message, 5000); }
  finally { $("send").disabled = false; }
}

// Интеграции открытого чата (владелец и админ): выбор → плашка «Перезапущу чат с новыми подключениями» 5 с с
// «Отменить» → /api/chat/mcp (запомнить у разговора и перезапустить окно с --resume — переписка та же).
export async function chatMcp(s) {
  try { MCP = (await api("/api/mcp")).servers || []; } catch (e) { return toast("Интеграции: " + e.message, 4000); }
  let off = [...(s.mcp_off || [])];
  const items = () => [...MCP.map((x) => {
    const on = x.ok && !off.includes(x.name);
    return { label: x.name, icon: !x.ok ? "warn" : on ? "check" : "x", on, sub: !x.ok ? "не отвечает" : on ? "включена" : "выключена в этом чате",
      run: () => { if (x.ok) off = on ? [...off, x.name] : off.filter((n) => n !== x.name); show(); } };
  }), { label: "Применить", icon: "refresh", sub: "чат перезапустится, переписка та же", run: apply }];
  const show = () => { helpSheet("sheet.chat-mcp"); sheet("Интеграции чата", items()); };
  const apply = () => {
    const same = JSON.stringify([...off].sort()) === JSON.stringify([...(s.mcp_off || [])].sort());
    if (same) return toast("Без изменений");
    let undone = false;
    const el = document.createElement("div"); el.className = "toast"; el.textContent = "Перезапущу чат с новыми подключениями через 5 с ";
    const b = document.createElement("button"); b.type = "button"; b.className = "toast-undo"; b.textContent = "Отменить";
    b.onclick = () => { undone = true; el.remove(); toast("Отменено"); }; el.append(b); notice(el);
    setTimeout(async () => {
      el.remove(); if (undone) return;
      try { const d = await api("/api/chat/mcp", { w: s.id, off }); toast("Чат перезапущен: " + (off.length ? "выключено " + off.length : "все интеграции включены")); await refresh(); if (d.id) openSession(d.id); }
      catch (e) { toast("Не вышло: " + e.message, 5000); }
    }, 5000);
  };
  show();
}
