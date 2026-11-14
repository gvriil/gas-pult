// Рабочий стол Ubuntu агентов (#206) — часть интерфейса по требованию (#191). Владелец 14.11: «чтобы внутри пульта
// была кнопочка … открыть Ubuntu сразу, минуя браузер, как мы ссылки открываем». Экран — поверх панели, внутри
// noVNC (iframe с того же адреса /desktop/…): видно браузер агента и можно им управлять. Вход: «Рабочий стол» →
// /api/desktop/open (свежему входу — код подтверждения) → cookie-пропуск на /desktop/ (iframe и WebSocket шлют только
// cookie; в Mini App вход идёт заголовком) → Caddy пускает только владельца (forward_auth /api/gate/desktop).

let deskEl = null;

async function deskOpen() {
  let d;
  try { d = await api("/api/desktop/open", {}); }
  catch (e) { return toast("Рабочий стол: " + e.message, 5000); }
  deskShow(d);
}

function deskShow(d) {
  deskClose();
  const el = deskEl = document.createElement("div");
  el.className = "desk"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Рабочий стол Ubuntu");
  el.innerHTML = `<div class="desk-bar"><b>${ic("monitor", "s16")}Рабочий стол Ubuntu</b><span class="desk-st" role="status">подключаю…</span>
      <button class="icon" data-desk="reload" aria-label="Переподключить" title="Переподключить">${ic("refresh")}</button>
      ${d.demo ? "" : `<button class="icon" data-desk="tab" aria-label="Открыть в браузере" title="Открыть в браузере">${ic("ext")}</button>`}
      <button class="icon" data-desk="close" aria-label="Закрыть" title="Закрыть">${ic("x")}</button></div>
    <iframe title="Рабочий стол Ubuntu" allow="clipboard-read; clipboard-write; fullscreen"></iframe>`;
  const fr = el.querySelector("iframe"), st = el.querySelector(".desk-st");
  if (d.demo) fr.srcdoc = `<body style="margin:0;display:grid;place-items:center;height:100vh;font:15px system-ui;background:#1e1e1e;color:#ddd;text-align:center">
    <div>Демо: здесь — рабочий стол Ubuntu<br>с браузером агента (noVNC)</div></body>`;
  else fr.src = d.url;
  fr.addEventListener("load", () => { st.textContent = d.demo ? "демо" : "на связи"; });
  el.addEventListener("click", (e) => {
    const b = e.target.closest("[data-desk]"); if (!b) return;
    if (b.dataset.desk === "close") return deskClose();
    if (b.dataset.desk === "tab") return openUrl(location.origin + d.url);
    st.textContent = "подключаю…"; deskOpen();             // переподключить: новый пропуск и заново noVNC
  });
  document.body.append(el); document.body.classList.add("desk-on");
  try { tg?.BackButton?.show(); tg?.BackButton?.onClick(deskClose); } catch (_) {}
  haptic("impactOccurred", "light");
}

function deskClose() {
  if (!deskEl) return;
  deskEl.remove(); deskEl = null; document.body.classList.remove("desk-on");
  try { tg?.BackButton?.offClick(deskClose); if (typeof view !== "undefined" && view === "home") tg?.BackButton?.hide(); } catch (_) {}
}

Object.assign(window, { deskOpen, deskClose });
