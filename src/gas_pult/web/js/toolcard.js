// Карточка вызова инструмента (#258, приём assistant-ui «Tool UI с подтверждением»): когда Claude просит разрешение
// (команда, правка файла, адрес, MCP), внизу переписки — карточка: что за действие, его параметры (команда или файл —
// поле ``target`` из /api/screen → humanize.parse) и кнопки «Да» / «Нет»; «Ещё» раскрывает все пункты меню Claude
// Code. Нажатие — те же /api/select и /api/key, что у списка вариантов. Список вариантов остаётся запасным путём:
// незнакомый диалог и меню без разбора — как раньше.
// Вопрос с вариантами (22.11: AskUserQuestion, доверие к папке, план, «Отправить ответы?») — карточка «Claude
// спрашивает»: вопрос и кнопки с текстом вариантов (разбор сервера — humanize.parse, он понимает и пояснения между
// пунктами, и черту перед «Chat about this»), одно нажатие — выбор; у вопроса агента — ещё «Отмена» (Esc).

const TC = { more: false, sig: "" };
const TC_KIND = { bash: "Команда на сервере", edit: "Правка файла", create: "Новый файл", overwrite: "Перезапись файла",
  notebook: "Правка блокнота", fetch: "Открыть адрес", search: "Поиск в интернете", mcp: "Инструмент MCP", read: "Чтение файлов" };

function toolCard(a) {
  if (!a || a.target === undefined || !TC_KIND[a.kind]) return "";
  if (a.sig !== TC.sig) Object.assign(TC, { more: false, sig: a.sig });
  const opts = a.options.map((o, i) => [o, i]).filter(([o]) => !o.send.show);
  const yes = opts.find(([o]) => o.key === "yes" || o.key === "yes-proceed") || opts.find(([o]) => o.level === 1 && /^yes/.test(o.key));
  const no = opts.find(([o]) => /^no/.test(o.key) || o.key === "deny");
  if (!yes || !no) return "";
  const rest = opts.filter((x) => x !== yes && x !== no);
  const btn = ([o, i], cls = "") => `<button class="opt ${cls}" data-tc="${i}"><span>${esc(o.label_ru)}</span></button>`;
  return `<div class="ask tc" data-help="${hv("sheet.toolcard")}"><p class="q">${ic("warn")}<span>Claude просит: ${esc(TC_KIND[a.kind].toLowerCase())}</span></p>
    ${a.target ? `<pre class="tc-target">${esc(a.target)}</pre>` : ""}
    <div class="tc-row">${btn(yes, "tc-yes")}${btn(no, "tc-no")}${rest.length ? `<button class="opt tc-more" data-tcmore="1" aria-expanded="${TC.more}"><span>${TC.more ? "Скрыть" : "Ещё"}</span></button>` : ""}</div>
    ${TC.more ? `<div class="tc-rest">${rest.map(([o, i]) => `<button class="opt" data-tc="${i}"><span>${esc(o.label_ru)}<small>${esc(o.note_ru || "")}</small></span></button>`).join("")}</div>` : ""}</div>`;
}

// Вопрос с вариантами. «Свой вариант» и «Обсудить» — Esc и курсор в поле (как в простом режиме); «Подробности» —
// экран терминала (в режиме кода он рядом). «Отмена» — только где Esc закрывает вопрос, а не Claude (не у доверия).
const CC_ESC = new Set(["question", "submit"]);
function choiceCard(a) {
  if (!a?.known || !a.options?.length) return "";
  const opts = a.options.map((o, i) => [o, i]).filter(([o]) => !o.send.show);
  if (!opts.length) return "";
  const q = a.title_ru || "Claude ждёт выбора";
  return `<div class="ask cc" data-help="${hv("sheet.toolcard")}"><p class="q">${ic("warn")}<span>${esc(q)}</span></p>
    ${opts.map(([o, i]) => `<button class="opt${o.level === 2 ? " l2" : ""}" data-tc="${i}"><span>${esc(o.label_ru)}${o.level === 2 && o.note_ru ? `<small>${esc(o.note_ru)}</small>` : ""}</span></button>`).join("")}
    ${CC_ESC.has(a.kind) && !a.options.some((o) => o.key === "cancel") ? `<button class="opt cc-esc" data-tcesc="1"><span>Отмена</span></button>` : ""}
    <p class="tip" id="askTip" hidden></p></div>`;
}

let tcAsk = null;                                       // последний разбор — для нажатий
function tcRender(a) { tcAsk = a; return a?.target !== undefined && TC_KIND[a.kind] ? toolCard(a) : choiceCard(a); }

$("ask").addEventListener("click", async (e) => {
  if (e.target.closest("[data-tcmore]")) { TC.more = !TC.more; e.stopPropagation(); return setAsk(toolCard(tcAsk), "tc" + tcAsk.sig + TC.more); }
  if (e.target.closest("[data-tcesc]")) { e.stopPropagation(); haptic("impactOccurred", "medium"); return press("Escape"); }
  const b = e.target.closest("[data-tc]"); if (!b || !tcAsk) return;
  e.stopPropagation();
  const o = tcAsk.options[+b.dataset.tc]; if (!o) return;
  haptic("impactOccurred", "medium");
  if (o.send.n) return choose(o.send.n, true, b);       // как второй тап по пункту списка: стрелки до пункта и Enter
  if (o.send.text) return pick(o.send.text, b);
  if (o.send.key) {
    await press(o.send.key);
    if (o.send.compose) { $("input").focus(); toast("Напишите Claude, что сделать иначе", 3500); }
  }
}, true);

const css = document.createElement("style");
css.textContent = `.ask.tc .tc-target { margin: 0 0 10px; padding: 8px 10px; background: var(--bg-terminal); color: #E8EAED;
  border-radius: var(--radius-sm); font: calc(13px * var(--fz, 1))/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: pre-wrap; word-break: break-word; max-height: 9.5em; overflow: auto; }
.ask.tc .tc-row { display: flex; gap: 8px; min-width: 0; }
.ask.tc .tc-row button.opt { width: auto; min-width: 0; flex: 1 1 0; justify-content: center; margin: 0; font-weight: 600; }
.ask.tc .tc-row button.opt.tc-more { flex: 0 0 auto; font-weight: 400; }
.ask.tc button.opt.tc-yes { background: var(--accent-primary); color: var(--on-accent); border-color: var(--accent-primary); }
.ask.tc .tc-rest { margin-top: 8px; }
.ask.tc .tc-rest small, .ask.cc small { display: block; color: var(--text-secondary); font-weight: 400; }
.ask.cc button.opt.l2 { border-style: dashed; }
.ask.cc button.opt.cc-esc { color: var(--text-secondary); justify-content: center; }`;
document.head.append(css);

Object.assign(window, { toolCard: tcRender });
