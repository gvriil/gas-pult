// Тур «Ладеи» для простого режима (владелец 25.11 через штаб): запуск одним нажатием «Показать тур», не больше пяти
// шагов простыми словами; последний — «Добавьте Ладею на экран «Домой»» с картинкой для iPhone (Поделиться → На экран
// «Домой») и Android (меню → Установить). Шаг «Домой» пропускается, если Ладея уже установлена (display-mode standalone,
// navigator.standalone) или открыта внутри Telegram. Шага, чьего элемента нет на экране, нет.
// Без внешних библиотек: подсветка — рамка вокруг элемента (затемнение — её тень), текст — карточка у края экрана.
// Движение — transform/opacity 200 мс; prefers-reduced-motion гасит его правилом ядра. Часть по требованию (#191).
const EN = () => LANG === "en";
const STEPS = [
  { sel: "#sComp", ru: ["Пишите как человеку", "Напишите задачу своими словами. Можно голосом — нажмите микрофон."],
    en: ["Write like to a person", "Describe the task in your own words. Or say it — tap the microphone."] },
  { sel: "#sAsk .ask, #sAsk .s-ask, #sAsk:not(:empty)", ru: ["Ваше «да» — одним нажатием",
    "Когда помощнику нужно разрешение, появится такая карточка. Нажмите «Да» — и он продолжит."],
    en: ["Your “yes” in one tap", "When the assistant needs permission, a card like this appears. Tap “Yes” and it carries on."] },
  { sel: "#sSecs:not([hidden])", ru: ["Частые задачи", "Разделы с готовыми задачами. Нажмите — помощник начнёт сам."],
    en: ["Common tasks", "Sections with ready-made tasks. Tap one and the assistant starts."] },
  { sel: "#sSet", ru: ["Настройки", "Почта, мессенджеры, тема и язык — здесь."],
    en: ["Settings", "Email, messengers, theme and language live here."] },
  { home: true, ru: ["Добавьте Ладею на экран «Домой»", "Так приложение не потеряется: откроется одним касанием, как любое другое."],
    en: ["Add Ladeya to your Home Screen", "So it doesn’t get lost: it opens in one tap, like any other app."] },
];
const T2 = (s) => (EN() ? s.en : s.ru);

const CSS = `
.lt-ring { position: fixed; z-index: 90; border-radius: 12px; pointer-events: none; box-shadow: 0 0 0 9999px rgba(12,12,11,.55);
  outline: 2px solid var(--accent-primary); outline-offset: 2px; transition: transform .2s ease, width .2s ease, height .2s ease; }
.lt-ring.none { outline: 0; width: 0 !important; height: 0 !important; left: 50% !important; top: 50% !important; }
.lt-card { position: fixed; z-index: 91; left: 50%; width: min(400px, calc(100vw - 24px)); transform: translateX(-50%);
  background: var(--bg-surface); color: var(--text-primary); border: 1px solid var(--border-subtle); border-radius: 16px;
  padding: 18px 18px 14px; box-shadow: 0 24px 48px rgba(0,0,0,.22); animation: lt-in .2s ease both; }
.lt-card.bottom { bottom: max(16px, env(safe-area-inset-bottom)); } .lt-card.top { top: max(16px, env(safe-area-inset-top)); }
.lt-card.mid { top: 50%; transform: translate(-50%, -50%); max-height: calc(100dvh - 32px); overflow: auto; }
@keyframes lt-in { from { opacity: 0; } to { opacity: 1; } }
.lt-card h3 { margin: 0 0 6px; font-size: calc(18px * var(--fz, 1)); font-weight: 600; letter-spacing: -.01em; }
.lt-card p { margin: 0 0 14px; color: var(--text-secondary); font-size: calc(15px * var(--fz, 1)); line-height: 1.45; }
.lt-row { display: flex; align-items: center; gap: 8px; }
.lt-row .n { margin-right: auto; color: var(--text-muted); font-size: calc(13px * var(--fz, 1)); }
.lt-card .btn { width: auto; min-height: 44px; padding: 0 18px; margin: 0; }
.lt-tabs { display: flex; gap: 6px; margin: 0 0 12px; }
.lt-tabs button { min-height: 36px; padding: 0 12px; border-radius: 8px; border: 1px solid var(--border-subtle); background: transparent;
  color: var(--text-secondary); font-weight: 500; }
.lt-tabs button[aria-pressed="true"] { color: var(--text-primary); border-color: var(--text-secondary); }
.lt-how { display: grid; grid-template-columns: 1fr auto 1fr auto 1fr; align-items: center; gap: 6px; margin: 0 0 12px; }
.lt-how .s { display: grid; justify-items: center; gap: 6px; padding: 10px 4px; border: 1px solid var(--border-subtle); border-radius: 12px;
  background: var(--bg-subtle); text-align: center; font-size: calc(12px * var(--fz, 1)); line-height: 1.25; color: var(--text-primary); min-height: 96px; }
.lt-how .s svg { width: 26px; height: 26px; color: var(--text-primary); }
.lt-how .s img { width: 34px; height: 34px; border-radius: 8px; }
.lt-how .a { color: var(--text-muted); }
.lt-how .hl { outline: 2px solid var(--accent-primary); outline-offset: 2px; border-radius: 6px; }
.lt-offer { margin: 12px 0; padding: 14px 16px 12px; border: 1px solid var(--border-subtle); border-radius: 14px;
  background: var(--bg-surface); animation: lt-in .2s ease both; }
.lt-offer b { display: block; font-size: calc(16px * var(--fz, 1)); margin: 0 0 4px; }
.lt-offer p { margin: 0 0 10px; color: var(--text-secondary); font-size: calc(14px * var(--fz, 1)); line-height: 1.45; }
.lt-offer .lt-row { justify-content: flex-end; } .lt-offer .btn { width: auto; min-height: 44px; padding: 0 16px; margin: 0; }
.lt-steps { margin: 0 0 14px; padding-left: 20px; color: var(--text-secondary); font-size: calc(14px * var(--fz, 1)); line-height: 1.45; }
`;
const SHARE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m8 7 4-4 4 4"/><path d="M6 11H5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-8a1 1 0 0 0-1-1h-1"/></svg>';
const PLUS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M12 8v8M8 12h8"/></svg>';
const DOTS = '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="12" cy="19" r="1.8"/></svg>';
const INST = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M12 7v7"/><path d="m9 11 3 3 3-3"/></svg>';
const ARROW = '<span class="a" aria-hidden="true">→</span>';
const APP = '<img src="/icon-192.png" alt="">';   // значок экрана «Домой» — из ladeya-app-icon.svg (tools/brand_images.py)

function how(os) {
  const en = EN();
  const box = (icon, text, hl) => `<div class="s"><span class="${hl ? "hl" : ""}">${icon}</span><span>${text}</span></div>`;
  if (os === "ios") return {
    pic: box(SHARE, en ? "Share" : "Поделиться", true) + ARROW + box(PLUS, en ? "Add to Home Screen" : "На экран «Домой»") + ARROW + box(APP, en ? "Ladeya" : "Ладея"),
    // Apple, «Добавление значка сайта на экран «Домой»»: support.apple.com/ru-ru/guide/iphone/iph42ab2f3a7/ios (25.11)
    steps: en ? ["Open this page in Safari.", "Tap the page menu ⋯, then tap Share.", "Scroll down and tap Add to Home Screen. Then tap Add."]
      : ["Откройте эту страницу в Safari.", "Нажмите кнопку меню страницы ⋯, затем «Поделиться».", "Прокрутите вниз, нажмите «На экран «Домой»», затем «Добавить»."] };
  return {
    pic: box(DOTS, en ? "More ⋮" : "Меню ⋮", true) + ARROW + box(INST, en ? "Install and create shortcut" : "Установить и создать ярлык") + ARROW + box(APP, en ? "Ladeya" : "Ладея"),
    // Google, «Как использовать веб-приложения» (Android): support.google.com/chrome/answer/9658361 (25.11)
    steps: en ? ["Open this page in Chrome.", "On the right of the address bar, tap More ⋮.", "Tap Install and create shortcut, then Install."]
      : ["Откройте эту страницу в Chrome.", "Справа от адресной строки нажмите ⋮.", "Нажмите «Установить и создать ярлык», затем «Установить»."] };
}

export const installed = () => {
  try { return matchMedia("(display-mode: standalone)").matches || navigator.standalone === true || !!tg?.initData; } catch (e) { return false; }
};
const visible = (el) => el && el.getClientRects().length && !el.closest("[hidden]");
const find = (sel) => [...document.querySelectorAll(sel)].find(visible);

let on = false;
export function start() {
  if (on) return;
  if (!document.getElementById("ltStyle")) {
    const s = document.createElement("style"); s.id = "ltStyle"; s.textContent = CSS; document.head.append(s);
  }
  const steps = STEPS.filter((s) => (s.home ? !installed() : !!find(s.sel)));
  if (!steps.length) return;
  on = true;
  const from = document.activeElement;
  const ring = document.createElement("div"); ring.className = "lt-ring"; ring.setAttribute("aria-hidden", "true");
  const card = document.createElement("div"); card.className = "lt-card"; card.setAttribute("role", "dialog"); card.setAttribute("aria-modal", "true");
  document.body.append(ring, card);
  let i = 0, os = /iPhone|iPad|iPod/.test(navigator.userAgent) ? "ios" : "android";
  const close = () => {
    on = false; ring.remove(); card.remove(); removeEventListener("keydown", key, true); removeEventListener("resize", paint);
    if (from?.isConnected) from.focus?.();
  };
  const key = (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } };
  function paint() {
    const st = steps[i], [title, text] = T2(st), last = i === steps.length - 1, en = EN();
    const el = st.home ? null : find(st.sel);
    if (el) {
      el.scrollIntoView?.({ block: "nearest" });
      const r = el.getBoundingClientRect(), p = 6;
      ring.className = "lt-ring"; Object.assign(ring.style, { left: r.left - p + "px", top: r.top - p + "px", width: r.width + 2 * p + "px", height: r.height + 2 * p + "px" });
      card.className = "lt-card " + (r.top + r.height / 2 > innerHeight / 2 ? "top" : "bottom");
    } else { ring.className = "lt-ring none"; card.className = "lt-card mid"; }
    let body = `<p>${esc(text)}</p>`;
    if (st.home) {
      const h = how(os);
      body += `<div class="lt-tabs" role="group" aria-label="${en ? "Phone" : "Телефон"}">${["ios", "android"].map((k) =>
        `<button type="button" data-lt-os="${k}" aria-pressed="${k === os}">${k === "ios" ? "iPhone" : "Android"}</button>`).join("")}</div>`
        + `<div class="lt-how" aria-hidden="true">${h.pic}</div><ol class="lt-steps">${h.steps.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>`;
    }
    const install = st.home && os === "android" && window.__ladeyaInstall;      // Chrome дал «Установить» — одна кнопка
    card.setAttribute("aria-label", title);
    card.innerHTML = `<h3>${esc(title)}</h3>${body}<div class="lt-row"><span class="n">${i + 1} ${en ? "of" : "из"} ${steps.length}</span>`
      + `<button class="btn quiet" type="button" data-lt-skip>${last ? (en ? "Later" : "Позже") : (en ? "Skip" : "Пропустить")}</button>`
      + (install ? `<button class="btn" type="button" data-lt-install>${en ? "Install" : "Установить"}</button>` : "")
      + `<button class="btn${install ? " quiet" : ""}" type="button" data-lt-next>${last ? (en ? "Done" : "Готово") : (en ? "Next" : "Далее")}</button></div>`;
    card.querySelector(install ? "[data-lt-install]" : "[data-lt-next]").focus();
  }
  card.addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.ltOs) { os = b.dataset.ltOs; return paint(); }
    if (b.hasAttribute("data-lt-skip")) return close();
    if (b.hasAttribute("data-lt-install")) {
      try { await window.__ladeyaInstall.prompt(); window.__ladeyaInstall = null; } catch (err) {}
      return close();
    }
    if (b.hasAttribute("data-lt-next")) { if (++i >= steps.length) return close(); paint(); }
  });
  addEventListener("keydown", key, true); addEventListener("resize", paint);
  paint();
}

// Предложение тура при первом входе (штаб 25.11): карточка «Показать тур» / «Не сейчас» под лентой простого
// режима — не модальное окно, читать и писать не мешает. Выбор помнится: на сервере (/api/tour, вид simple — у каждого
// свой) и на устройстве (store) — по ссылке, где сервер отметку не принимает, хватит устройства. Один раз.
const OFFER_KEY = "tour:simple";
function remember(state) {
  store(OFFER_KEY, state);
  api("/api/tour", { tour: "simple", state }).catch(() => {});
}
export async function offer() {
  if (store(OFFER_KEY) || document.getElementById("ltOffer") || !SIM.on) return;
  try { const t = await api("/api/tour"); if (t?.simple) return store(OFFER_KEY, t.simple); } catch (e) { /* нет ответа — решит устройство */ }
  const feed = $("sFeed"); if (!feed || !SIM.on) return;
  if (!document.getElementById("ltStyle")) {
    const s = document.createElement("style"); s.id = "ltStyle"; s.textContent = CSS; document.head.append(s);
  }
  const box = document.createElement("div"); box.id = "ltOffer"; box.className = "lt-offer"; box.setAttribute("role", "region");
  box.setAttribute("aria-label", L("tour.offer.title", "Показать, как тут всё устроено?"));
  box.innerHTML = `<b>${esc(L("tour.offer.title", "Показать, как тут всё устроено?"))}</b>`
    + `<p>${esc(L("tour.offer.text", "Минута, пять шагов. Последний — как добавить Ладею на экран «Домой»."))}</p>`
    + `<div class="lt-row"><button class="btn quiet" type="button" data-lt-no>${esc(L("tour.offer.no", "Не сейчас"))}</button>`
    + `<button class="btn" type="button" data-lt-go>${esc(L("help.tour", "Показать тур"))}</button></div>`;
  box.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    box.remove();
    if (b.hasAttribute("data-lt-go")) { remember("done"); start(); } else remember("dismissed");
  });
  feed.after(box);                                    // под сообщениями, у поля ввода — видно и при длинной истории
  box.scrollIntoView?.({ block: "nearest" });
}
