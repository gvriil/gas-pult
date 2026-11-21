// Ссылки и терминал (решение владельца 17.11) — часть по требованию (#191).
// 1. Ссылка в переписке у владельца (есть рабочий стол Ubuntu) — шторка «Где открыть?»: «В Ubuntu» (вкладка в Chrome
//    рабочего стола, /api/desktop/url, затем рабочий стол), «Здесь» (как раньше), «Копировать». «Запомнить для этого
//    сайта» (по умолчанию да) — выбор хранится на сервере по сайту, дальше ссылки сайта открываются без вопроса.
//    Сброс — «Настройки» → «Ссылки: где открывать». Владелец: «спрашивать один раз и запоминать».
// 2. «Терминал» рядом с «Ubuntu»: живой терминал окна tmux ubuntu-shell (bash в домашней папке); нет — создаётся.

let LP = null;                                          // {сайт: "desk" | "here"} — с сервера, один раз
const hostOf = (href) => { try { return new URL(href).host.toLowerCase(); } catch (e) { return ""; } };
async function prefs() { if (!LP) LP = (await api("/api/links/prefs").catch(() => ({ sites: {} }))).sites || {}; return LP; }

function openHere(href) { openLink(href) || window.open(href, "_blank", "noopener,noreferrer"); }

async function openDesk(href) {
  try { await api("/api/desktop/url", { url: href }); }
  catch (e) { return toast("Не открыл в Браузере: " + e.message, 5000); }
  toast("Открыл в Chrome на рабочем столе");
  part("desktop").then(() => deskOpen(), (er) => toast("Рабочий стол не загрузился: " + er.message, 4500));
}

async function remember(host, where) {
  try { LP = (await api("/api/links/prefs", { host, open: where })).sites; } catch (e) { toast(e.message, 4000); }
}

async function linkChoose(href) {
  const host = hostOf(href), got = (await prefs())[host];
  if (got === "desk") return openDesk(href);
  if (got === "here") return openHere(href);
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.linkwhere");
  bg.innerHTML = `<div class="sheet" role="dialog" aria-label="Где открыть ссылку"><h3>Где открыть?</h3>
    <p class="note" style="margin:0 16px 6px;word-break:break-all">${esc(href)}</p>
    <button data-lw="desk">${ic("monitor")}<span>В Браузере<small>Браузер агентов — там ваши входы и агенты</small></span></button>
    <button data-lw="here">${ic("ext")}<span>Здесь<small>в браузере этого устройства</small></span></button>
    <button data-lw="copy">${ic("copy")}<span>Копировать</span></button>
    <label class="lw-mem" style="display:flex;gap:10px;align-items:center;margin:8px 16px"><input type="checkbox" id="lwMem" checked>
      <span>Запомнить для ${esc(host)}<small style="display:block;color:var(--text-secondary)">сбросить — «Настройки» → «Ссылки: где открывать»</small></span></label>
    <button class="cancel" data-close>Закрыть</button></div>`;
  document.body.append(bg);
  bg.addEventListener("click", async (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) return bg.remove();
    const b = e.target.closest("[data-lw]"); if (!b) return;
    const w = b.dataset.lw, mem = bg.querySelector("#lwMem").checked;
    bg.remove();
    if (w === "copy") return copyText(href, LT("link.copied", "Ссылка скопирована"));
    if (mem && host) await remember(host, w);
    return w === "desk" ? openDesk(href) : openHere(href);
  });
}

async function linkPrefsSheet() {
  LP = null; const d = await prefs(), sites = Object.entries(d);
  helpSheet("settings.links");
  sheet("Ссылки: где открывать", sites.length ? [
    { info: true, icon: "globe", label: "Запомненные сайты", sub: "нажмите — забыть: при следующей ссылке спрошу снова" },
    ...sites.map(([h, w]) => ({ label: h, icon: w === "desk" ? "monitor" : "ext", sub: w === "desk" ? "в Браузере" : "здесь",
      run: async () => { await remember(h, null); toast("Забыл " + h); linkPrefsSheet(); } }))]
    : [{ info: true, icon: "globe", label: "Запомненных сайтов нет", sub: "выбор появится после первой ссылки с галочкой «Запомнить»" }]);
}

async function shellOpen() {
  let d;
  try { d = await api("/api/shell/open", {}); } catch (e) { return toast("Терминал не открылся: " + e.message, 5000); }
  ttyOpen(d.id);
}

Object.assign(window, { linkChoose, openDesk, linkPrefsSheet, shellOpen });
