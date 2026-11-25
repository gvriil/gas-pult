// Тема одной кнопкой (владелец 25.11 через штаб): солнце / луна в правом верхнем углу на каждом экране, без захода
// в настройки; выбор помнится на устройстве (store("theme")), по умолчанию — как в системе. «Как в системе» вернуть —
// «Настройки» → «Тема». Часть по требованию (#191): ядро не растёт.
const SUN = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>';
const MOON = '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/>';
const dark = () => document.documentElement.dataset.theme === "dark";

function paint(b) {
  const d = dark();
  b.innerHTML = `<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d ? SUN : MOON}</svg>`;
  b.setAttribute("aria-label", d ? "Светлая тема" : "Тёмная тема");
  b.title = d ? "Светлая тема" : "Тёмная тема";
}

function button(id) {
  const b = document.createElement("button");
  b.type = "button"; b.className = "icon"; b.id = id;
  b.onclick = () => { store("theme", dark() ? "light" : "dark"); applyTheme(); document.querySelectorAll(".theme-btn").forEach(paint); };
  b.classList.add("theme-btn"); paint(b);
  return b;
}

export function init() {
  if (document.getElementById("themeTop")) return;
  $("settingsBtn")?.before(button("themeTop"));      // полный режим и вход: шапка
  $("sSet")?.before(button("themeSimple"));          // простой режим
  // тема могла смениться иначе (система, «Настройки») — значок следом
  new MutationObserver(() => document.querySelectorAll(".theme-btn").forEach(paint))
    .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
}
