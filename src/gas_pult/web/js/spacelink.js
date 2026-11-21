// «Ссылка на пространство» (GAS-38, владелец 21.11): полная панель одного пространства по ссылке — проекты, чаты,
// «Новый чат», настройки панели — как у тестировщика этого пространства. Срок, число устройств, права, название.
// Владелец: группа «Пространства» → «Ссылка» или «Настройки» → «Фокус-ссылки» → «Ссылка на пространство».
// На устройстве по ссылке — полоса под шапкой: чья панель, до какого числа, «только чтение». Часть: part("spacelink").

const TTLS = [["1h", "1 час"], ["1d", "1 день"], ["7d", "7 дней"], ["30d", "30 дней"], ["none", "Без срока"]];
const MAXES = [[1, "1"], [3, "3"], [0, "Без ограничения"]];
const RIGHTS = [["full", "Полные"], ["read", "Только чтение"]];
// для кого (штаб 21.11): клиент соглашается с условиями сам — строкой при первом действии; себе и тестировщику — нет
const AUD = [["client", "Для клиента"], ["self", "Для себя или тестировщика"]];
const day = (t) => new Date(t * 1000).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });

// Подпись условий: «до 28 нояб.» / «без срока»; «входов 2 из 3»; «только чтение»
export function terms(x, opened) {
  const till = x.forever ? "без срока" : "до " + day(x.exp);
  const dev = opened == null ? (x.max ? `до ${x.max} ${plural(x.max, ["устройства", "устройств", "устройств"])}` : "устройств без ограничения")
    : !opened ? "ещё не открыта" : x.max ? `входов ${opened} из ${x.max}` : `входов ${opened}`;
  return [till, dev, x.rights === "read" ? "только чтение" : "полные права"].join(" · ");
}

function group(key, title, items, val) {
  return `<div class="section">${esc(title)}</div><div class="scn-opts" role="group" aria-label="${esc(title)}">${items.map(([v, label]) =>
    sChip(String(v) === String(val), `data-sg="${key}" data-sv="${esc(String(v))}"`, label)).join("")}</div>`;
}

export async function form(slug) {
  if (!spacesInfo) await loadSpaces();
  const list = (spacesInfo?.tenants || []).filter((t) => t.ready !== false);
  if (!list.length) return toast("Пространств пока нет", 4000);
  // По умолчанию — 7 дней, 3 устройства (телефон, браузер Telegram, компьютер), полные права
  const o = { space: list.some((t) => t.slug === slug) ? slug : list[0].slug, ttl: "7d", max: 3, rights: "full", audience: "client" };
  const html = `${list.length > 1 ? group("space", "Пространство", list.map((t) => [t.slug, t.title || t.slug]), o.space) : `<p class="note">Пространство «${esc(list[0].title || list[0].slug)}»: проекты, чаты, «Новый чат», настройки панели. Окон и настроек пульта по ссылке не видно.</p>`}
    <div class="field"><label for="slName">Название</label>
      <input id="slName" maxlength="60" autocomplete="off" placeholder="${esc((list.find((t) => t.slug === o.space) || list[0]).title || "")}" enterkeyhint="go">
      <div class="hint">Видно вам в списке ссылок и человеку — над панелью.</div></div>
    ${group("ttl", "Срок", TTLS, o.ttl)}${group("max", "Сколько устройств", MAXES, o.max)}${group("rights", "Права", RIGHTS, o.rights)}${group("audience", "Для кого", AUD, o.audience)}
    <p class="note" id="slNote"></p>
    <button class="btn wide" type="button" data-sgo="1">${ic("qr")}Создать ссылку</button>`;
  const note = () => { $("slNote").textContent = o.rights === "read" ? "Только чтение: человек видит проекты и переписку, но не пишет и не создаёт чаты." : "Полные права: пишет помощнику, создаёт чаты и проекты — только в этом пространстве."; };
  const bg = sSheet("sheet.focus", "Ссылка на пространство", html, async (b) => {
    if (b.dataset.sg) {
      const k = b.dataset.sg;
      o[k] = typeof o[k] === "number" ? Number(b.dataset.sv) : b.dataset.sv;
      b.parentElement.querySelectorAll(".scn-opt").forEach((x) => {
        const on = x === b; x.classList.toggle("on", on); on ? x.setAttribute("aria-pressed", "true") : x.removeAttribute("aria-pressed");
      });
      if (k === "space") $("slName").placeholder = list.find((t) => t.slug === o.space)?.title || "";
      return note();
    }
    if (!b.dataset.sgo) return;
    await busy(b, "Создаю…", async () => {
      try {
        const d = await api("/api/focus/new", { ...o, name: $("slName").value.trim(), base: location.origin });
        bg.remove(); ready(d);
      } catch (e) { toast("Не вышло: " + e.message, 5000); }
    });
  });
  note();
  $("slName").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); bg.querySelector("[data-sgo]").click(); } };
}

// Готово: ссылка, «Скопировать», QR, «Отозвать». Токен виден только здесь — в списке ссылок его нет.
function ready(d) {
  copyText(d.url, "Ссылка скопирована");
  const bg = sSheet("sheet.focus", "Ссылка на «" + d.name + "»", `
    <p class="note">${esc(terms(d))}. Откройте ссылку на нужном устройстве — там будет панель пространства «${esc(d.space_title || d.space)}». Отозвать — здесь или «Настройки» → «Фокус-ссылки».</p>
    <div class="scn-opts">${sChip(true, 'data-scp="1"', "Скопировать ссылку", ic("copy"))}</div>
    <div class="inv-url" id="slUrl"></div>
    <img class="focus-qr" id="slQr" alt="QR-код ссылки">
    <div class="scn-opts">${sChip(false, 'data-srv="1"', "Отозвать эту ссылку", ic("x"))}</div>`, async (b) => {
    if (b.dataset.scp) return copyText(d.url, "Ссылка скопирована");
    if (b.dataset.srv) {
      try { await api("/api/focus/revoke", { id: d.id }); bg.remove(); toast("Ссылка отозвана — устройства отключены"); } catch (e) { toast(e.message, 5000); }
    }
  }, "Готово");
  bg.querySelector("#slUrl").textContent = d.url;
  const qr = bg.querySelector("#slQr");             // QR — POST: адрес с токеном не попадает в журнал прокси
  if (DEMO) return qr.remove();
  api("/api/focus/qr", { url: d.url }).then((b) => { if (b instanceof Blob) qr.src = URL.createObjectURL(b); else qr.remove(); }).catch(() => qr.remove());
}

// Устройство по ссылке: под шапкой — «Пространство «…» · до 28 нояб. · только чтение»
export function bar(x) {
  const el = $("focusExp"); if (!el || !x) return;
  const soon = !x.forever && x.exp * 1000 - Date.now() < 2 * 864e5;
  el.className = "focus-exp" + (soon ? " soon" : "");
  el.innerHTML = `<span>${ic("flask", "s16")}<b>${esc(x.name || "Пространство")}</b></span><span>${ic(soon ? "warn" : "lock", "s16")}${esc(x.forever ? "без срока" : "до " + day(x.exp))}</span>`
    + (x.rights === "read" ? `<span>${ic("eye", "s16")}только чтение</span>` : "")
    // ссылка «для клиента»: согласие — строкой, без отдельного экрана; первое действие — согласие
    + (x.terms_line ? `<span class="sl-terms">Продолжая, вы принимаете <a href="/terms" target="_blank" rel="noopener" style="color:var(--accent-primary)">условия использования</a></span>` : "");
  el.hidden = false;
}
