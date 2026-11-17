// Приглашения v2 (владелец 17.11: «пригласить пользователя: роль, срок; не одноразово — тестировать на телефоне и
// компьютере»). Владелец выбирает роль, срок ссылки, число входов и срок доступа человека → ссылка, QR и код.
// Сервер: POST /api/invite/new {space, role, ttl, uses, access}. Часть грузится по требованию: part("invite").

const ROLES = [["member", "Участник — пишет агентам"], ["viewer", "Наблюдатель — только смотрит"]];
const TTLS = [["1d", "24 часа"], ["7d", "7 дней"], ["30d", "30 дней"], ["90d", "90 дней"], ["365d", "Год"]];
const USES = [[1, "Один вход"], [5, "До 5 входов"], [0, "Без лимита"]];
const ACCESS = [[0, "Бессрочно"], [30, "30 дней"], [60, "60 дней"], [365, "Год"]];

function group(name, items, val) {
  return `<div class="section">${esc(name)}</div><div class="scn-opts">${items.map(([v, label]) =>
    sChip(String(v) === String(val), `data-ig="${esc(name)}" data-iv="${esc(String(v))}"`, label)).join("")}</div>`;
}

export function inviteForm(t) {
  const o = { role: "member", ttl: "7d", uses: 0, access: 0 };   // по умолчанию — для тестов: неделя, многоразово
  const keys = { "Роль": "role", "Ссылка действует": "ttl", "Сколько входов": "uses", "Доступ человека": "access" };
  const html = () => `<p class="note">Одну ссылку можно открыть на телефоне и на компьютере — для этого выберите
    несколько входов. Каждый вход без Telegram — отдельный гость в «Людях». Через Telegram человек входит на любом
    устройстве сам.</p>
    ${group("Роль", ROLES, o.role)}${group("Ссылка действует", TTLS, o.ttl)}${group("Сколько входов", USES, o.uses)}
    ${group("Доступ человека", ACCESS, o.access)}
    <p class="note">Доступ человека — сколько он пользуется пультом после входа. Продлить или отключить —
    «Настройки» → «Люди».</p>
    <button class="btn wide" type="button" data-igo="1">${ic("mail")}Создать приглашение</button>`;
  const bg = sSheet(hv("sheet.space-invite"), "Пригласить в «" + (t.title || t.slug) + "»", html(), async (b) => {
    if (b.dataset.ig) {
      const k = keys[b.dataset.ig];
      o[k] = typeof o[k] === "number" ? Number(b.dataset.iv) : b.dataset.iv;
      b.parentElement.querySelectorAll(".scn-opt").forEach((x) => {
        const on = x === b; x.classList.toggle("on", on); on ? x.setAttribute("aria-pressed", "true") : x.removeAttribute("aria-pressed");
      });
      return;
    }
    if (!b.dataset.igo) return;
    b.disabled = true;
    try { bg?.remove?.(); inviteReady(await api("/api/invite/new", { space: t.slug, ...o }), t.title || t.slug); }
    catch (e) { b.disabled = false; toast("Не вышло: " + e.message, 4000); }
  });
}

// Подпись под готовым приглашением: срок, входы, доступ — словами
export function inviteTerms(r) {
  const ttl = { 86400: "24 часа", 604800: "7 дней", 2592000: "30 дней", 7776000: "90 дней", 31536000: "год" }[r.ttl] || "24 часа";
  const uses = r.uses === 0 ? "входов — без лимита" : r.uses > 1 ? `до ${r.uses} входов` : "один вход: после него ссылка и код сгорают";
  const acc = r.access ? `доступ — ${r.access} дней после входа` : "доступ бессрочный";
  return `Ссылка — ${ttl}, ${uses}; ${acc}.`;
}
