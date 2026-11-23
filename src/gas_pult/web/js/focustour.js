// Тур по фокус-чату (владелец 23.11: «должны отображаться все функции»): «⋯» → «Тур по экрану» на устройстве по
// фокус-ссылке. Шесть шагов: поле ввода, кнопки вариантов, «Сообщить об ошибке», «На другом устройстве», чаты, «⋯».
// Шаг показывает то, что сейчас на экране: нет вопроса — попап по центру «где появятся кнопки»; нет кнопки — шаг
// пропускается. driver.js — тот же, что у общего тура (loadDriver в ядре: cdnjs, точная версия, SRI).
// Отметки «пройден» и «отклонён» — только в этом браузере (localStorage, ключ — id записи ссылки, не токен). Нового
// пути на сервере нет: фокус-ссылке не нужен ещё один путь записи (docs/SECURITY.md), а потеря отметки стоит одного
// лишнего предложения тура.

const KEY = () => "gp.ftour:" + (meta?.focus?.id || "demo");
export const mark = (v) => (v ? store(KEY(), v) : store(KEY()));

const vis = (sel) => [...document.querySelectorAll(sel)].find((el) => el.getClientRects().length && !el.closest("[hidden]")) || null;

function steps() {
  const ask = vis("#ask button") ? vis("#ask > *") || vis("#ask") : null;
  const bug = vis("#bugBtn"), menu = vis("#menuBtn"), more = vis("#chatMoreBtn");
  const chats = split() ? vis("#nav") : vis("#navBtn") || vis("#target");
  return [
    { el: vis("#input") && vis("#composer"), title: "Поле ввода", text: "Напишите вопрос или задачу. Нажмите «Отправить». Микрофон справа — ввод голосом." },
    ask ? { el: ask, title: "Кнопки вариантов", text: "Агент задал вопрос. Нажмите кнопку с нужным ответом — он уйдёт сразу." }
      : { el: null, title: "Кнопки вариантов", text: "Когда агент задаст вопрос, над полем ввода появятся кнопки с вариантами. Нажмите нужную — ответ уйдёт сразу." },
    bug ? { el: bug, title: "Сообщить об ошибке", text: "Что-то не работает? Нажмите эту кнопку и напишите, что не так. Снимок экрана приложится сам." }
      : menu ? { el: menu, title: "Сообщить об ошибке", text: "Откройте это меню и выберите «Сообщить об ошибке». Снимок экрана приложится сам." } : null,
    { el: vis("[data-fdev]"), title: "На другом устройстве", text: "Откройте этот чат на компьютере или планшете: QR-код и ссылка на 15 минут." },
    { el: chats, title: "Чаты", text: FOCUS_PROJ() ? "Список чатов проекта. Выберите чат или начните новый." : "Список чатов по этой ссылке. Сейчас в нём один чат — этот." },
    { el: more, title: "Меню «⋯»", text: "Все действия с чатом: название, удобства, этот тур. Тур можно пройти снова в любое время." },
  ].filter((s) => s && (s.el || s.title === "Кнопки вариантов"));
}

let on = false;
export async function start() {
  if (on || tourOn) return;
  document.getElementById("ftourOffer")?.remove();
  document.querySelectorAll(".sheet-bg").forEach((x) => x.remove()); closeMenu();
  const from = document.activeElement;
  let drv;
  try { drv = await loadDriver(); } catch (e) { return toast("Тур недоступен — нет связи", 3500); }
  const list = steps();
  if (!list.length) return;
  mark("done");
  on = tourOn = true;
  await new Promise((done) => {
    const d = drv({
      showProgress: true, progressText: "Фокус-чат · {{current}} из {{total}}", nextBtnText: "Далее", prevBtnText: "Назад",
      doneBtnText: "Готово", popoverClass: "gp-tour", overlayColor: "#000", overlayOpacity: 0.5,
      stagePadding: 6, stageRadius: 12, smoothScroll: false, allowKeyboardControl: true,
      steps: list.map((s) => ({ ...(s.el ? { element: s.el } : {}), popover: { title: esc(s.title), description: esc(s.text) } })),
      onPopoverRender: (p) => p.closeButton.setAttribute("aria-label", "Закрыть тур"),
      onDestroyed: () => done(),
    });
    d.drive();
  }).finally(() => { on = tourOn = false; });
  if (from?.isConnected && from !== document.body && !document.querySelector(".sheet-bg")) from.focus?.();
}

// Предложение один раз: «Пройти короткий тур?» — над полем ввода, как у общего тура (класс .tour-offer)
export function offer() {
  if (mark() || document.getElementById("ftourOffer") || FOCUS_DEMO()) return;
  const box = document.createElement("div"); box.className = "tour-offer"; box.id = "ftourOffer";
  box.setAttribute("role", "dialog"); box.setAttribute("aria-label", "Предложение пройти тур");
  box.innerHTML = `<div class="row">${ic("spark")}<div class="ctext"><b>Пройти короткий тур?</b>
      <div class="meta">Минута — что есть на этом экране. Потом — «⋯» → «Тур по экрану».</div></div>
      <button class="icon" data-no aria-label="Не сейчас">${ic("x", "s16")}</button></div>
    <div class="acts"><button class="btn quiet sm" data-no>Не сейчас</button><button class="btn sm" data-go>Пройти</button></div>`;
  const no = () => { box.remove(); mark("dismissed"); };
  box.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.hasAttribute("data-no")) return no();
    if (b.hasAttribute("data-go")) { box.remove(); start(); }
  });
  box.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); no(); } });
  notice(box);
}
