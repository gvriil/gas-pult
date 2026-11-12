// ---------- расход (usage.py): токены и деньги по журналам Claude Code, лимиты, пауза ----------
// Сервер показывает расход только хозяину учётки: владельцу — его пул, участнику — его папку Claude.
let costInfo = null;                                  // итог дня, лимиты (владельцу) — d.cost из /api/sessions
const usd = (x) => x == null ? "цена неизвестна" : "$" + (x >= 100 ? Math.round(x) : x.toFixed(2));
const tok = (n) => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n || 0);
// откуда цена (usage.py, задача 51): прайс Anthropic, счёт OpenRouter или оценка по тарифу Z.ai / DeepSeek
const costSrc = (c) => ({ estimate: "оценка: токены × цены поставщика (Z.ai, DeepSeek)", provider: "по счёту OpenRouter", anthropic: "по ценам API Anthropic" })[c?.cost_source] || "по ценам API";
const estTag = (c) => c?.cost_source === "estimate" ? " · оценка" : "";
const tokLine = (c) => `ввод ${tok(c.tokens.in)} · вывод ${tok(c.tokens.out)} · кэш: запись ${tok(c.tokens.cw)}, чтение ${tok(c.tokens.cr)}`;
function costChip(s) {
  const c = s.cost;
  if (!c || !c.total) return "";
  const near = c.limit && c.usd != null && c.usd >= c.limit * 0.8;
  const title = `Расход сессии ${costSrc(c)}: ${tokLine(c)}${c.pending ? ` · ${c.pending} отв. ждут счёта OpenRouter` : c.unknown ? " · часть ответов — модели без цены" : ""}${s.cost.by ? " · открыл(а) " + (c.by.name || c.by.id) : ""}`;
  return `<span class="chip cost${near ? " warn" : ""}" title="${esc(title)}">${ic("coin")}${c.usd == null ? "цена ?" : usd(c.usd) + estTag(c)} · ${tok(c.total)}${c.limit ? " из $" + c.limit : ""}${c.by ? " · " + esc(c.by.name || "участник") : ""}</span>`;
}
function costBar(s) {
  if (!s.cost_paused) return "";
  const p = s.cost?.paused, own = meta?.role === "owner" && p;
  const what = p ? `${p.kind === "day" ? "за сегодня по учётке" : "в этой сессии"} потрачено <b>${usd(p.spent)}</b> (лимит $${Number(p.limit).toFixed(2)})` : "";
  const ask = own ? (p.state === "stopped" ? " Вы решили остановить." : " Продолжить?") : " Решает владелец — новые сообщения в неё не отправляются.";
  return `<div class="costbar" data-costbar>${ic("pause", "s16")}<div class="t"><b>На паузе по расходу</b>${what ? ": " + what : ""}.${ask}
    ${own ? `<div class="acts"><button class="btn sm" data-cost-go="${esc(s.id)}">${ic("play", "s16")}Продолжить, +лимит</button>${p.state !== "stopped" ? `<button class="btn quiet sm" data-cost-stop="${esc(s.id)}">Остановить</button>` : ""}</div>` : ""}</div></div>`;
}
function costSummary() {
  const c = costInfo;
  if (c?.budget) {                                    // пространство: запас на период (задача 35)
    const b = c.budget;
    return `<button class="chip cost${b.pct >= 0.8 ? " warn" : ""}" data-cost-sum data-tour="cost" title="${esc(b.text)}">${ic("coin")}${esc(T("bud.chip", { t: usd(b.today), l: usd(b.left) }))}</button>`;
  }
  if (!c?.today) return "";
  const lim = c.limits?.day, over = lim && c.today.usd != null && c.today.usd >= lim * 0.8;
  return `<button class="chip cost${over ? " warn" : ""}" data-cost-sum data-tour="cost" title="Расход за сегодня по вашей учётке, ${esc(costSrc(c.today))}">${ic("coin")}Сегодня <b>${c.today.usd == null ? "цена ?" : usd(c.today.usd)}</b>${lim ? " из $" + lim : ""}${estTag(c.today)}</button>`;
}
async function costDecide(id, act, btn) {
  await busy(btn, act === "go" ? "Продолжаю…" : "…", async () => {
    try { const r = await api("/api/cost/decide", { w: id, act }); toast(r.result, 4000); haptic("notificationOccurred", "success"); await refresh(); }
    catch (e) { toast(e.message); }
  });
}
function costClick(e) {                               // кнопки плашки — на карточке и в сессии
  const g = e.target.closest("[data-cost-go]"), st = e.target.closest("[data-cost-stop]");
  if (g) { costDecide(g.dataset.costGo, "go", g); return true; }
  if (st) { costDecide(st.dataset.costStop, "stop", st); return true; }
  return !!e.target.closest("[data-costbar]");
}
function costSheet() {
  const c = costInfo, own = meta?.role === "owner";
  if (!c) return toast("Расход появится после первого ответа Claude");
  const lim = c.limits || {};
  helpSheet("settings.cost");
  sheet("Расход", [
    ...(c.budget ? [{ info: true, icon: "coin", label: c.budget.text, sub: T("bud.sub", { r: usd(c.budget.reserve), d: c.budget.period_days }) }] : []),
    { info: true, icon: "coin", label: `Сегодня: ${c.today.usd == null ? "цена неизвестна" : usd(c.today.usd)}${estTag(c.today)} · ${tok(c.today.total)} токенов`, sub: tokLine(c.today) + (c.today.pending ? ` · ${c.today.pending} отв. ждут счёта OpenRouter` : c.today.unknown ? " · часть ответов — модели без цены" : "") },
    ...(own ? [{ info: true, icon: "pause", label: `Лимит на сессию: ${lim.session ? "$" + lim.session : "выключен"}`, sub: "превысила — пауза и вопрос вам в боте и здесь" },
               { info: true, icon: "wait", label: `Лимит на день: ${lim.day ? "$" + lim.day : "выключен"}`, sub: "по вашей учётке за сегодня (местное время сервера)" },
               { label: "Изменить лимиты", icon: "edit", run: limitsForm }] : []),
    { info: true, icon: "help", label: "Как считаем", sub: `По журналам Claude Code. Модели Claude — по прайсу API Anthropic (сверено ${c.prices_checked}); с подпиской Pro/Max это оценка, а не счёт. OpenRouter — по его счёту за каждый ответ (приходит через несколько секунд). GLM (Z.ai) и DeepSeek — оценка: токены × цены поставщика${c.provider_prices_checked ? " (сверено " + c.provider_prices_checked + ")" : ""}. Цену, которую показывает сам Claude Code для чужих моделей, не берём — он считает их по тарифам Anthropic. Шлюзы GigaChat и YandexGPT — только токены. ${own ? "Сессии участников на их собственных учётках сюда не входят." : "Здесь — только ваша учётка Claude."}` },
  ]);
}
async function limitsForm() {
  let cur = { limits: costInfo?.limits || {} };
  try { cur = await api("/api/cost/limits"); } catch (e) { /* покажем то, что знаем */ }
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("settings.limits");
  const v = (x) => x == null ? "" : String(x);
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Лимиты расхода</h3>
    <div class="field" style="margin:4px 16px 10px"><label for="limS">На одну сессию, $</label><input id="limS" inputmode="decimal" autocomplete="off" placeholder="выключен" value="${esc(v(cur.limits.session))}"></div>
    <div class="field" style="margin:0 16px 0"><label for="limD">На день по вашей учётке, $</label><input id="limD" inputmode="decimal" autocomplete="off" placeholder="выключен" value="${esc(v(cur.limits.day))}"></div>
    <p class="note" id="limErr" style="margin:8px 16px 0">Пусто или 0 — без лимита. Превышение: Claude останавливается, сообщения в сессию не уходят, пока вы не решите — в боте или здесь.</p>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="limOk">Сохранить</button></div></div>`;
  document.body.append(bg);
  $("limOk").onclick = async () => {
    try { const r = await api("/api/cost/limits", { session: $("limS").value.trim(), day: $("limD").value.trim() });
          if (costInfo) costInfo.limits = r.limits; bg.remove(); toast("Лимиты сохранены"); haptic("notificationOccurred", "success"); refresh(); }
    catch (e) { $("limErr").textContent = e.message; $("limErr").style.color = "var(--status-danger)"; }
  };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
}
$("costPause").addEventListener("click", costClick);
// переключение на запасного поставщика (бот сделал сам) — одна строка, один раз
const fbSeen = new Set();
function fallbackNotices(list) {
  let seen = ""; try { seen = localStorage.getItem("fbSeen") || ""; } catch (e) { /* без хранилища — только в памяти */ }
  const fresh = list.filter((x) => !fbSeen.has(x.ts) && String(x.ts) > seen);
  list.forEach((x) => fbSeen.add(x.ts));
  if (!fresh.length) return;
  toast(fresh.at(-1).text, 6000);
  try { localStorage.setItem("fbSeen", String(fresh.at(-1).ts)); } catch (e) { /* не страшно */ }
}
async function refresh() {
  lastPoll = Date.now();
  try {
    const pv = projOn() && (navOn() || projMode() && !$("home").hidden);   // панель чатов и «Проекты» — тот же опрос, ответ шире
    const d = await api(pv ? "/api/projects" : "/api/sessions");
    if (pv) projData = d;
    await dictReady;                                   // отрисовка (чипы запаса, «+ добавить») — из словаря (T); запрос — сразу
    sessions = d.sessions.filter((x) => !NAV.gone.has(x.id)); costInfo = d.cost || null; agoSkew = d.now ? d.now - Date.now() / 1000 : 0;
    watchSessions(sessions); fallbackNotices(d.fallback || []);
    checkBuild(d);
    if (view === "session" && cur()?.rev) store(seenKey(cur()), cur().rev);   // вы в сессии — значит, видели
    // Без «обновлено ЧЧ:ММ:СС» (план UX, пункт 9): о связи говорит только плашка «Нет связи»; текст не меняется
    // каждый опрос — меньше перерисовок.
    const hostLine = d.host || "";
    if ($("brandSub").textContent !== hostLine) { $("brandSub").textContent = hostLine; $("navHome").title = "Главная: сессии и проекты · " + hostLine; }
    if (view === "home" && homeView !== "integrations" && $("subtitle").textContent !== hostLine) setSub(`<span>${esc(hostLine)}</span>`);
    renderRail(); renderNav();
    if (!$("home").hidden) {
      const n = (k) => sessions.filter((s) => s.status === k).length;
      if (homeView === "sessions" && !projMode()) {
        const sorted = [...sessions].sort(byChange);             // ждущие ответа (и пауза по расходу) — сверху
        const mine = (x) => meta?.role === "owner" && x.space;     // владельцу окна пространств — своей группой ниже
        morph($("sessionsView"), notifyCard() + (sessions.length ? `<div class="summary" data-tour="sessions">
            ${n("dialog") ? `<span class="chip s-approval"><b>${n("dialog")}</b> ждут ответа</span>` : ""}
            <span class="chip s-running"><b>${n("busy")}</b> работают</span><span class="chip"><b>${n("idle")}</b> свободны</span>${n("stopped") ? `<span class="chip"><b>${n("stopped")}</b> остановлены</span>` : ""}${costSummary()}</div>`
            + pinGroups(sorted.filter((x) => !mine(x)), card) : '<div class="empty" data-tour="sessions">Сессий с Claude пока нет — нажмите «Новая сессия».</div>') + spacesGroup(sorted.filter(mine)) + scnEntry());
      }
      if (homeView === "sessions" && projMode()) {
        if (!projData) { projData = await api("/api/projects"); }
        renderProjects();
      }
      if (homeView === "commands") loadCommands(true);
    }
    if (view !== "session" || DRAFT) return;            // новый чат до первой отправки — сессии ещё нет
    const s = cur();
    // фокус: сессию перезапустили (модель, поставщик) — окно новое, сервер отдаёт его; завершённая — 410 (focusEnd)
    if (FOCUS) focusExp();                              // срок входа — раз в опрос (минуты меняются)
    if (!s) { if (FOCUS_PROJ()) return current ? focusGone() : focusEmpty(); if (FOCUS) return sessions.length ? openSession(sessions[0].id) : focusEnd("Сессия завершена."); toast("Сессия завершена"); return back(); }
    paintSession(s); loadHint(s);
    if (lastStatus === "busy" && s.status !== "busy") { haptic("notificationOccurred", "success"); loadContent(); }   // вкладку не дёргаем
    else if (tab === "screen" || s.status === "dialog" || s.status === "stopped" || lastStatus === "stopped") loadContent();
    else liveChat();
    lastStatus = s.status;
  } catch (e) { if (view !== "login" && !e.net) setSub(`<span style="color:var(--status-danger)">ошибка: ${esc(e.message)}</span>`); }   // обрыв сети — плашка через 15 с
}
// Шапка и строка «куда пишете» — чтобы никогда не отправить в чужую сессию.
function paintSession(s) {
  moneyBar(s);
  const st = ST[s.status];
  if (split()) setText($("title"), s.name);
  else {                                            // телефон: имя ▾ — шторка сессий; точка — что-то ждёт в другой сессии
    const sig = sessions.some((x) => x.id !== s.id && (x.status === "dialog" || isNew(x)));
    setHTML($("title"), `<span class="nm">${esc(s.name)}</span><span class="caret">${ic("chev", "s16")}</span>${sig ? '<span class="sig" title="Что-то ждёт в другой сессии"></span>' : ""}`);
  }
  // «изменена N назад»: на широком экране — в шапке; на телефоне шапка занята статусом и кнопками — в строке
  // «куда пишете» вместо повтора статуса (он остаётся в шапке и цветом точки)
  const ag = agoSpan(s, true);
  setSub(`<span class="chip ${st.cls}"><span class="sdot ${st.cls}"></span>${st.label}</span>${provChip(s)}${spaceChips(s)}<span>${s.model ? esc(s.model) + " · " : ""}${esc(folder(s.path))}${s.branch && s.branch !== "HEAD" ? " · " + esc(s.branch) : ""}${ctxUsed(s) == null ? "" : " · контекст " + ctxUsed(s) + "%"}${s.cost?.total ? " · " + (s.cost.usd == null ? tok(s.cost.total) + " токенов" : usd(s.cost.usd) + (s.cost.cost_source === "estimate" ? " (оценка)" : "")) : ""}</span>${split() ? ag : ""}`);
  const cb = costBar(s); setHidden($("costPause"), !cb); setHTML($("costPause"), cb);     // пауза по расходу — над полем ввода
  setHTML($("target"), `<span class="sdot ${st.cls}"></span><b>${esc(s.name)}</b><span class="caret">${ic("chev", "s16")}</span><span>${provName(s) ? esc(provName(s)) + " · " : ""}${split() || !ag ? st.label : ""}</span>${split() ? "" : ag}`);
  const ph = hint || "Сообщение для " + s.name + "…";     // куда уйдёт — видно в поле; подсказка Claude — вместо
  if ($("input").placeholder !== ph) $("input").placeholder = ph;
  paintWorking(s);
  paintGaps(s);                                     // что недоступно у поставщика сессии (задача 38)
}
function sessionsClick(e) {
  if (costClick(e)) return;
  if (e.target.closest("[data-cost-sum]")) return costSheet();
  if (e.target.closest("[data-space-task]")) return spaceTaskForm();
  if (e.target.closest("[data-space-invite]")) return spaceInvite();
  if (e.target.closest("[data-space-closed]")) return ssPickSpace(ssClosed);
  if (e.target.closest("[data-space-add]")) return budgetAdd(e.target.closest("[data-space-add]").dataset.spaceAdd);
  if (e.target.closest("[data-scn-home]")) return scenariosView();
  const r = e.target.closest("[data-reply]"); if (r) return openSession(r.dataset.reply, "screen");
  const v = e.target.closest("[data-revive]"); if (v) return revive(v.dataset.revive, v);
  const k = e.target.closest("[data-more-s]"); if (k) return sessionSheet(k.dataset.moreS);
  const ro = e.target.closest("[data-roff]"); if (ro) return repoOff(ro.dataset.roffS, ro.dataset.roff, ro);
  const sc = e.target.closest("[data-sched]"); if (sc) { const s = sessions.find((x) => x.id === sc.dataset.sched); return s && scheduleSheet(s); }
  const c = e.target.closest(".card[data-id]"); if (c) openSession(c.dataset.id);
}
$("sessionsView").addEventListener("click", sessionsClick);
// До первого ответа сервера — скелетоны (план UX, пункт 3); первая отрисовка (morph / innerHTML) их заменит.
morph($("sessionsView"), skelCards(3)); $("projectsView").innerHTML = skelCards(3);
$("navList").innerHTML = `<div class="skel nav-skel" aria-hidden="true">${[70, 52, 64, 45].map((w) => `<i style="width:${w}%"></i>`).join("")}</div>`;
$("newBtn").onclick = () => navOn() && projOn() && meta?.role !== "viewer" ? newChat(projMode() && proj ? proj : undefined)   // как ✎ в панели чатов
  : projMode() && proj ? projectNew() : newSession();
