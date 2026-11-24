// «Смотреть, 1 мин»: ролик над демо (/?demo — QR в инвест-питче, 24.11). Стили — здесь, ядро не растёт.
const CSS = `.demo .dv-btn { margin-left: 6px; font: inherit; font-weight: 600; color: var(--on-accent); background: var(--accent-primary);
border: 0; border-radius: var(--radius-sm); padding: 3px 10px; cursor: pointer; }
.dv-bg { position: fixed; inset: 0; z-index: 60; background: rgba(17,17,16,.86); display: flex; align-items: center; justify-content: center; padding: 16px; }
.dv-bg video { max-width: 100%; max-height: calc(100dvh - 88px); border-radius: var(--radius-md); background: var(--bg-terminal); }
.dv-bg .dv-x { position: absolute; top: 12px; right: 12px; min-width: 44px; min-height: 44px; border-radius: var(--radius-sm);
border: 0; background: var(--bg-surface); color: var(--text-primary); font: inherit; font-weight: 600; cursor: pointer; padding: 0 14px; }`;
if (!document.getElementById("dvCss")) {
  const st = document.createElement("style"); st.id = "dvCss"; st.textContent = CSS; document.head.append(st);
}
// Ролик «Смотреть, 1 мин» над демо — часть по требованию (#191), грузится только в демо (24.11: QR в инвест-питче ведёт на /?demo). Файл кладёт владелец вне git —
// нет файла, нет кнопки. Сеть — обычный fetch: /api/demo/info отвечает и без входа.
export function init() {
  fetch("/api/demo/info").then((r) => r.json()).then((d) => {
    if (!d?.video || $("dvBtn")) return;
    const b = document.createElement("button");
    b.type = "button"; b.id = "dvBtn"; b.className = "dv-btn"; b.textContent = "Смотреть, 1 мин";
    b.onclick = () => {
      const bg = document.createElement("div"); bg.className = "dv-bg"; bg.setAttribute("role", "dialog"); bg.setAttribute("aria-label", "Ролик о Гавриле");
      bg.innerHTML = `<video src="${esc(d.video)}" controls autoplay playsinline preload="metadata"></video><button class="dv-x" type="button">Закрыть</button>`;
      const close = () => { bg.querySelector("video")?.pause(); bg.remove(); removeEventListener("keydown", esc_); b.focus(); };
      const esc_ = (e) => e.key === "Escape" && close();
      bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest(".dv-x")) close(); });
      addEventListener("keydown", esc_);
      document.body.append(bg); bg.querySelector(".dv-x").focus();
    };
    $("demoBar").querySelector("span")?.after(b);
    document.documentElement.style.setProperty("--demo-h", $("demoBar").offsetHeight + "px");
  }).catch(() => {});
}
