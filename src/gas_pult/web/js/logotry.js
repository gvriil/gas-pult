// Примерка знака (штаб 26.11): /?logo — арфа на 16, 24, 32, 48, 96, 192 px (файл по лесенке размеров) и название
// RU / EN, на светлом и тёмном фоне. Для проверки владельцем и снимков; без входа.
const SIZES = [16, 24, 32, 48, 96, 192];
const file = (px, dark) => (px < 24 ? "/favicon.svg" : "/brand/ladeya-mark" + (px < 48 ? "-small" : px < 96 ? "-m" : px >= 192 ? "-xl" : "") + (dark ? "-dark" : "") + ".svg");
function panel(dark) {
  const bg = dark ? "#0C0C0B" : "#F4F4F2", fg = dark ? "#F4F4F2" : "#232326", d = dark ? "-dark" : "";
  const marks = SIZES.map((px) => `<figure><img src="${px < 24 ? (dark ? "/favicon-32-dark.png" : "/favicon-32.png") : file(px, dark)}" style="height:${px}px;width:auto" alt=""><figcaption>${px}</figcaption></figure>`).join("");
  const lock = (h, lang) => `<div class="lk"><img src="${file(h * 1.6 < 24 ? 24 : h * 1.6, dark)}" style="height:${Math.round(h * 1.6)}px" alt=""><img src="/brand/wordmark-${lang}${d}.svg" style="height:${h}px" alt=""></div>`;
  return `<section style="background:${bg};color:${fg}"><h2>${dark ? "Тёмная тема" : "Светлая тема"}</h2><div class="row">${marks}</div>`
    + `<div class="row">${lock(15, "ru")}${lock(15, "en")}</div><div class="row">${lock(40, "ru")}</div><div class="row">${lock(40, "en")}</div></section>`;
}
export function start() {
  const st = document.createElement("style");
  st.textContent = `#logotry{position:fixed;inset:0;z-index:2147483000;overflow:auto;background:#888;font:14px/1.4 system-ui,sans-serif}
#logotry section{padding:16px}#logotry h2{margin:0 0 12px;font-size:16px;font-weight:600}
#logotry .row{display:flex;flex-wrap:wrap;gap:18px;align-items:flex-end;margin:0 0 18px}
#logotry figure{margin:0;display:flex;flex-direction:column;align-items:center;gap:4px}#logotry figcaption{font-size:11px;opacity:.6}
#logotry .lk{display:flex;align-items:center;gap:.5em}`;
  const box = document.createElement("div"); box.id = "logotry";
  box.innerHTML = panel(false) + panel(true);
  document.head.append(st); document.body.append(box);
}
