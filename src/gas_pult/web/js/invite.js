// Приглашение одной ссылкой (владелец 17.11; отзыв тестировщика: «я рассчитываю на обычную ссылку — нажал —
// сработало», «зачем тут телеграм»). Владелец: имя → «Создать ссылку» (роль, срок, устройства — в «Ещё настройки»)
// → «Отправить в Telegram» / «Скопировать». Человек: ссылка → «Здравствуйте, <имя>!» → «Начать» → внутри.
// Telegram — мягко, один раз, после первого ответа помощника (tgOffer). Часть грузится по требованию: part("invite").

const ROLES = [["member", "Участник — пишет помощнику"], ["viewer", "Наблюдатель — только смотрит"]];
const TTLS = [["1d", "24 часа"], ["7d", "7 дней"], ["30d", "30 дней"], ["90d", "90 дней"], ["365d", "Год"]];
const USES = [[1, "1"], [3, "3"], [10, "10"], [0, "Без лимита"]];
const ACCESS = [[0, "Бессрочно"], [30, "30 дней"], [60, "60 дней"], [365, "Год"]];
const TTL_TEXT = { 86400: "24 часа", 604800: "7 дней", 2592000: "30 дней", 7776000: "90 дней", 31536000: "год" };

function group(key, title, items, val) {
  return `<div class="section">${esc(title)}</div><div class="scn-opts">${items.map(([v, label]) =>
    sChip(String(v) === String(val), `data-ig="${key}" data-iv="${esc(String(v))}"`, label)).join("")}</div>`;
}

export function inviteForm(list) {
  // По умолчанию (владелец 17.11: «1 да, 2 да»): 7 дней, 3 устройства, доступ бессрочно; без имени — «Гость»
  const o = { space: list[0].slug, role: "member", ttl: "7d", uses: 3, access: 0 };
  const spaces = list.length > 1 ? group("space", "Куда", list.map((t) => [t.slug, t.title || t.slug]), o.space) : "";
  const html = `<div class="field"><label for="invWho" class="inv-big">Как зовут человека?</label>
      <input id="invWho" class="inv-in" maxlength="60" autocomplete="off" placeholder="Например, Алексей" enterkeyhint="go">
      <div class="hint">Он увидит: «Здравствуйте, Алексей!». Можно оставить пустым — будет «Гость».</div></div>
    ${spaces}
    <button class="btn wide" type="button" data-igo="1">${ic("mail")}Создать ссылку</button>
    <details class="inv-more"><summary>Ещё настройки — роль, срок, устройства</summary>
      ${group("role", "Роль", ROLES, o.role)}${group("ttl", "Ссылка работает", TTLS, o.ttl)}
      ${group("uses", "На скольких устройствах", USES, o.uses)}${group("access", "Доступ человека", ACCESS, o.access)}
      <p class="note">Ссылка — это и есть вход: кто её получил, тот войдёт. Поэтому у неё срок и лимит устройств, а о
      каждом новом устройстве вам придёт сообщение. Отключить человека — «Настройки» → «Люди».</p>
    </details>`;
  const bg = sSheet(hv("sheet.space-invite"), "Пригласить человека", html, async (b) => {
    if (b.dataset.ig) {
      const k = b.dataset.ig;
      o[k] = typeof o[k] === "number" ? Number(b.dataset.iv) : b.dataset.iv;
      b.parentElement.querySelectorAll(".scn-opt").forEach((x) => {
        const on = x === b; x.classList.toggle("on", on); on ? x.setAttribute("aria-pressed", "true") : x.removeAttribute("aria-pressed");
      });
      return;
    }
    if (!b.dataset.igo) return;
    const name = $("invWho").value.trim(), t = list.find((x) => x.slug === o.space) || list[0];
    b.disabled = true;
    try {
      const r = await api("/api/invite/new", { ...o, name });
      bg.remove(); inviteSend(r, name || "Гость", t.title || t.slug);
    } catch (e) { b.disabled = false; toast("Не вышло: " + e.message, 4000); }
  });
  $("invWho").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); bg.querySelector("[data-igo]").click(); } };
  setTimeout(() => $("invWho")?.focus(), 80);
}

// Готово: отправить ссылку. Текст — без кода и инструкций: «нажмите ссылку — и вы внутри».
function inviteSend(r, who, title) {
  const link = location.origin + r.path;
  const text = `${who === "Гость" ? "Здравствуйте" : who}, вот ваш помощник: нажмите ссылку — и вы внутри.`;
  const share = "https://t.me/share/url?url=" + encodeURIComponent(link) + "&text=" + encodeURIComponent(text);
  sSheet(hv("sheet.invite-ready"), "Ссылка для «" + who + "» готова", `
    <p class="note">${esc(inviteTerms(r))} Пространство — «${esc(title)}».</p>
    <div class="scn-opts">${sChip(true, 'data-ish="1"', "Отправить в Telegram", ic("send"))}${sChip(false, 'data-icp="1"', "Скопировать ссылку", ic("copy"))}</div>
    <div class="inv-url">${esc(link)}</div>
    <details class="inv-more"><summary>QR и код — если ссылку не открыть</summary>
      ${invQr(link)}<div class="inv-codebig">${esc(r.code || "")}</div>
      <p class="note">Код вводят на экране входа: «Есть код приглашения?». Отозвать — gas-pult invite revoke ${esc(r.hint || "")}</p>
    </details>`, (b) => {
    if (b.dataset.ish) tg?.openTelegramLink ? tg.openTelegramLink(share) : window.open(share, "_blank", "noopener");
    if (b.dataset.icp) copyText(text + "\n" + link, "Ссылка скопирована");
  });
}

// Подпись условий словами — и для готового приглашения, и для ссылки входа (inviteReady в ядре)
export function inviteTerms(r) {
  const ttl = TTL_TEXT[r.ttl] || "24 часа";
  const dev = r.uses === 0 ? "на любом числе устройств" : r.uses === 1 ? "на одном устройстве" : `на ${r.uses} устройствах`;
  const acc = r.access ? `доступ — ${r.access} дней после входа` : "доступ бессрочный";
  return `Ссылка работает ${ttl}, ${dev}; ${acc}.`;
}

// Гость без Telegram, после первого ответа помощника — один раз: «ответы в телефон?»
export function tgOffer() {
  store("tgOffer", "1");
  const bg = sSheet(hv("settings.device"), "Получать ответы помощника в телефон?", `
    <p class="note">Подключите Telegram — ответы будут приходить туда, даже когда эта страница закрыта.
    Можно пропустить: позже — «Настройки» → «Вход с другого устройства».</p>
    <div class="scn-opts tg-offer">${sChip(true, 'data-tgy="1"', "Подключить Telegram", ic("send"))}</div>
    <div id="tgOfferOut"></div>`, (b) => { if (b.dataset.tgy) linkTelegram($("tgOfferOut"), bg); }, "Не сейчас");
}
