// Первый экран простого режима (штаб 26.11, аудит Atoms, п. 1): у пустого чата — «Что поручим сегодня?», три готовые
// задачи и выбор «Для себя · Для бизнеса». Задача — одно нажатие: текст встаёт в поле ввода, второе — «Отправить»
// (правило «не больше двух нажатий»). Ничего не отправляется само. Выбор «для себя / для бизнеса» помнит браузер.
// Владельцу экран не показывается, пока он сам не включит: localStorage firstScreen=1 (экран владельца не меняем);
// в демо — показывается всем.
// Часть по требованию (#191): в ядре — только контейнер #sFirst и вызов fill().

const TXT = {
  ru: {
    h: "Что поручим сегодня?",
    sub: "Выберите задачу — текст встанет в поле, останется нажать «Отправить». Или напишите своими словами.",
    self: "Для себя", biz: "Для бизнеса", aria: "Для кого задачи",
    t: {
      self: [["Разобрать почту", "Разбери мою почту за сегодня: что важно, на что ответить, что можно отложить."],
        ["Спланировать день", "Спланируй мой день: дела, встречи и что сделать в первую очередь."],
        ["Подготовить отчёт", "Подготовь короткий отчёт: что я сделал за неделю и что осталось."]],
      biz: [["Разобрать почту", "Разбери рабочую почту: заявки, счета, вопросы клиентов — что срочно и кому ответить."],
        ["Спланировать день", "Спланируй рабочий день: встречи, задачи команды и сроки — что сделать в первую очередь."],
        ["Подготовить отчёт", "Подготовь отчёт за неделю: продажи, заказы, выводы и что сделать дальше."]],
    },
  },
  en: {
    h: "What shall we do today?",
    sub: "Pick a task — the text goes into the field, then tap Send. Or write in your own words.",
    self: "For me", biz: "For business", aria: "Who the tasks are for",
    t: {
      self: [["Sort my email", "Sort my email for today: what matters, what to answer, what can wait."],
        ["Plan my day", "Plan my day: tasks, meetings and what to do first."],
        ["Prepare a report", "Prepare a short report: what I did this week and what is left."]],
      biz: [["Sort my email", "Sort the work inbox: leads, invoices, customer questions — what is urgent and who to answer."],
        ["Plan my day", "Plan the work day: meetings, team tasks and deadlines — what to do first."],
        ["Prepare a report", "Prepare a weekly report: sales, orders, conclusions and next steps."]],
    },
  },
};
const CSS = `
#sFirst { text-align: center; padding: 28px 8px 8px; }
#sFirst h2 { margin: 0 0 6px; font-size: calc(22px * var(--fz, 1)); font-weight: 600; letter-spacing: -.01em; color: var(--text-primary); }
#sFirst .fs-sub { margin: 0 auto 14px; max-width: 34em; color: var(--text-secondary); font-size: calc(14px * var(--fz, 1)); }
#sFirst .scn-opts { justify-content: center; }
#sFirst .fs-mode { margin: 0 0 12px; }
#sFirst .fs-tasks button { min-height: 44px; }
`;
const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

export const allowed = (role, demo) => role !== "viewer" && (demo || role !== "owner" || store("firstScreen") === "1");

export function fill(box, lang = "ru") {
  if (!document.getElementById("fsStyle")) {
    const st = document.createElement("style"); st.id = "fsStyle"; st.textContent = CSS; document.head.append(st);
  }
  const L = TXT[lang] || TXT.ru, mode = store("fsMode") === "self" ? "self" : "biz";
  const chip = (on, attrs, label) => `<button class="scn-opt${on ? " on" : ""}" type="button" ${attrs}${on ? ' aria-pressed="true"' : ""}>${esc(label)}</button>`;
  box.innerHTML = `<h2>${esc(L.h)}</h2><p class="fs-sub">${esc(L.sub)}</p>`
    + `<div class="scn-opts fs-mode" role="group" aria-label="${esc(L.aria)}">${chip(mode === "self", 'data-fmode="self"', L.self)}${chip(mode === "biz", 'data-fmode="biz"', L.biz)}</div>`
    + `<div class="scn-opts fs-tasks">${L.t[mode].map(([label], i) => chip(false, `data-ftask="${i}"`, label)).join("")}</div>`;
  if (box.dataset.bound) return;
  box.dataset.bound = "1";
  box.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    e.stopPropagation();                               // не уходит в общий обработчик простого режима
    if (b.dataset.fmode) { store("fsMode", b.dataset.fmode); return fill(box, lang); }
    if (b.dataset.ftask) {
      const L2 = TXT[lang] || TXT.ru, m = store("fsMode") === "self" ? "self" : "biz", t = document.getElementById("sInput");
      if (!t) return;
      t.value = L2.t[m][+b.dataset.ftask][1];
      t.dispatchEvent(new Event("input", { bubbles: true }));   // поле подрастёт и черновик сохранится — как при наборе
      t.focus();
    }
  });
}
