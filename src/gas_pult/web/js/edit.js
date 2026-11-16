// Правка своего сообщения (#258, приём assistant-ui «Edit message»): голос распознался с ошибкой или опечатка —
// «Изменить» у своего сообщения → текст в поле ввода, над полем полоска «Исправляете сообщение · Отмена». Отправка —
// в ту же сессию с пометкой, что это исправление: Claude ответит заново на правильный текст. Прошлый ответ не
// откатываем: в Claude Code это /rewind — интерактивное меню, через окно tmux делать его ненадёжно.

let EDIT = null;                                        // { orig } — что исправляем

function editBar(on) {
  let bar = $("editBar");
  if (!on) { bar?.remove(); return padDock(); }
  if (!bar) {
    bar = document.createElement("div"); bar.id = "editBar"; bar.className = "edit-bar"; bar.setAttribute("role", "status");
    bar.innerHTML = `${ic("edit", "s16")}<span>Исправляете сообщение — Claude ответит заново</span><button type="button" class="link" data-editx="1">Отмена</button>`;
    $("composer").before(bar);                           // над полем ввода, внутри нижней панели
    bar.addEventListener("click", (e) => { if (e.target.closest("[data-editx]")) editCancel(); });
  }
  padDock();
}

function editMsg(text) {
  if (!text) return toast("Не нашёл текст сообщения");
  EDIT = { orig: text };
  const inp = $("input"); inp.value = text; inp.dispatchEvent(new Event("input")); inp.focus();
  try { inp.setSelectionRange(text.length, text.length); } catch (e) {}
  editBar(true); haptic("impactOccurred", "light");
}

function editCancel() { EDIT = null; editBar(false); $("input").value = ""; $("input").dispatchEvent(new Event("input")); }

// sendText ядра зовёт перед отправкой: исправление — с пометкой; тот же текст без правок — как есть
function editFix(typed) {
  if (!EDIT) return typed;
  const same = typed.trim() === EDIT.orig.trim();
  EDIT = null; editBar(false);
  return same ? typed : "Исправление моего предыдущего сообщения — оно было распознано или написано с ошибкой. "
    + "Ответь заново на правильный текст:\n\n" + typed;
}

const css = document.createElement("style");
css.textContent = `.edit-bar { display: flex; align-items: center; gap: 8px; padding: 6px 12px; margin: 0 0 6px;
  background: var(--accent-soft); color: var(--text-primary); border-radius: var(--radius-md); font-size: calc(13px * var(--fz, 1)); }
.edit-bar span { flex: 1; } .edit-bar .link { white-space: nowrap; }`;
document.head.append(css);

Object.assign(window, { editMsg, editFix, editCancel });
