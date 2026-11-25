// Самопроверка буфера обмена (25.11): /?clipdiag — открыть на iPhone в Safari, в Telegram и на ПК, нажать 5 кнопок,
// сделать один снимок экрана или скопировать итог. Без входа: страница ничего не читает с сервера, кроме этой части.
const R = {};                                          // итог по проверкам: имя → «да» / «нет: причина»
const NAMES = {
  now: "1. Копировать сразу (writeText)",
  later: "2. Копировать после сети — новый способ (ClipboardItem)",
  old: "3. Копировать после сети — старый способ (await, затем writeText)",
  range: "4. Запасной путь iPhone (выделение + execCommand)",
  read: "5. Прочитать буфер (кнопка «Вставить»)",
  paste: "Вставка долгим нажатием в поле",
};
const net = () => fetch("/js/clipdiag.js?t=" + Date.now(), { cache: "no-store" }).then(() => "Ладэя: проверка после сети " + new Date().toLocaleTimeString());
const why = (e) => "нет: " + (e?.name || "") + (e?.message ? " — " + e.message : "");

const TESTS = {
  now: () => navigator.clipboard.writeText("Ладэя: проверка сразу").then(() => "да"),
  later: () => navigator.clipboard.write([new ClipboardItem({ "text/plain": net().then((t) => new Blob([t], { type: "text/plain" })) })]).then(() => "да"),
  old: async () => { const t = await net(); await navigator.clipboard.writeText(t); return "да"; },
  range: () => {
    const s = document.createElement("span");
    s.textContent = "Ладэя: запасной путь"; s.contentEditable = "true";
    s.style.cssText = "position:fixed;top:0;left:0;opacity:0;white-space:pre;-webkit-user-select:text;user-select:text";
    document.body.append(s);
    const r = document.createRange(); r.selectNodeContents(s); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
    let ok = false; try { ok = document.execCommand("copy"); } catch (e) {}
    sel.removeAllRanges(); s.remove();
    return Promise.resolve(ok ? "да" : "нет: execCommand вернул false");
  },
  read: () => navigator.clipboard.readText().then((t) => t ? "да: «" + t.slice(0, 40) + "»" : "нет: пусто"),
};

function env() {
  const t = window.Telegram?.WebApp;
  return [
    "Браузер: " + navigator.userAgent,
    "Telegram: " + (t?.platform && t.platform !== "unknown" ? t.platform + " " + (t.version || "") : "нет"),
    "Защищённое соединение: " + (window.isSecureContext ? "да" : "нет"),
    "clipboard.writeText: " + (navigator.clipboard?.writeText ? "есть" : "нет") +
      " · ClipboardItem: " + (window.ClipboardItem ? "есть" : "нет") +
      " · readText: " + (navigator.clipboard?.readText ? "есть" : "нет"),
  ];
}
const summary = () => ["Самопроверка буфера — " + new Date().toLocaleString(), ...env(), "",
  ...Object.keys(NAMES).map((k) => NAMES[k] + ": " + (R[k] || "не нажимали"))].join("\n");

export function start() {
  const st = document.createElement("style");
  st.textContent = `
#clipdiag{max-width:560px;margin:0 auto;position:fixed;inset:0;z-index:2147483000;overflow:auto;background:var(--bg,#F4F4F2);color:var(--text,#111);
  font:15px/1.4 var(--font,system-ui,sans-serif);padding:16px 16px 40px}
#clipdiag h1{font-size:20px;margin:0 0 4px}#clipdiag p{margin:0 0 12px;color:var(--muted,#5C5B55)}
#clipdiag .row{display:flex;flex-direction:column;gap:4px;margin:0 0 10px}
#clipdiag button{width:100%;min-height:44px;padding:0 14px;border-radius:10px;border:1px solid var(--line,rgba(17,17,17,.15));
  background:var(--card,#fff);color:inherit;font:inherit;cursor:pointer;text-align:left}
#clipdiag button.main{background:var(--accent,#C2361A);color:var(--on-accent,#fff);border:0;width:100%;text-align:center;font-weight:600}
#clipdiag .res{font-size:13px;padding:0 4px;overflow-wrap:anywhere}
#clipdiag .ok{color:var(--ok,#1F7A3A)}#clipdiag .bad{color:var(--accent,#C2361A)}
#clipdiag textarea{width:100%;min-height:56px;box-sizing:border-box;border-radius:10px;border:1px solid var(--line,rgba(17,17,17,.15));
  background:var(--card,#fff);color:inherit;font:inherit;padding:10px}
#clipdiag pre{white-space:pre-wrap;font-size:12px;background:var(--card,#fff);border-radius:10px;padding:10px;margin:12px 0}`;
  const box = document.createElement("div");
  box.id = "clipdiag";
  box.innerHTML = `<h1>Проверка буфера обмена</h1>
<p>Нажмите кнопки 1–5 по очереди. Потом вставьте что-нибудь в поле долгим нажатием. В конце — «Скопировать итог» или снимок экрана.</p>
${Object.keys(TESTS).map((k) => `<div class="row"><button data-t="${k}">${NAMES[k].replace(/ \(.*\)$/, "")}</button><span class="res" id="cd-${k}"></span></div>`).join("")}
<textarea id="cd-in" placeholder="Нажмите и удерживайте здесь → «Вставить»"></textarea>
<div class="row"><span class="res" id="cd-paste"></span></div>
<pre id="cd-sum"></pre>
<button class="main" id="cd-copy">Скопировать итог</button>`;
  document.head.append(st); document.body.append(box);
  const show = () => {
    for (const k of Object.keys(NAMES)) {
      const el = box.querySelector("#cd-" + k);
      if (el && R[k]) { el.textContent = R[k]; el.className = "res " + (R[k].startsWith("да") ? "ok" : "bad"); }
    }
    box.querySelector("#cd-sum").textContent = summary();
  };
  box.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-t]"); if (!b) return;
    const k = b.dataset.t; R[k] = "…"; show();
    let p; try { p = TESTS[k](); } catch (err) { p = Promise.reject(err); }   // вызов — синхронно, в самом нажатии
    p.then((v) => { R[k] = v; }, (err) => { R[k] = why(err); }).then(show);
  });
  box.querySelector("#cd-in").addEventListener("paste", (e) => {
    const t = e.clipboardData?.getData("text") || "";
    R.paste = t ? "да: «" + t.slice(0, 40) + "»" : "нет: пусто"; setTimeout(show, 0);
  });
  box.querySelector("#cd-copy").addEventListener("click", () => copyText(summary(), "Итог скопирован"));
  show();
}
