// Черновики действий коннекторов в «Ждут вашего Да» (drafts.py, штаб 21.11): МойСклад, Битрикс24, WB, Ozon, почта,
// календарь, Мак. Агент сам ничего не меняет в сервисе — он готовит черновик; человек решает здесь:
// «Да» — отметка ровно этому черновику, и в чат, откуда он пришёл, уходит «выполни»; «Изменить» — черновик снимается,
// чат открывается с началом ответа в поле; «Нет» — черновик снимается. Видно только свои черновики (владельца или
// своего пространства) — это проверяет сервер.

const SVC = { moysklad: "МойСклад", bitrix24: "Битрикс24", wildberries: "Wildberries", ozon: "Ozon", mail: "Почта",
  cal: "Календарь", tgbiz: "Telegram для бизнеса", cdek: "СДЭК", docs: "Документы", mac: "Компьютер",
  telegram: "Telegram", signal: "Signal", whatsapp: "WhatsApp" };
let list = [], at = 0, busy = false;

export const svcName = (s) => SVC[s] || s;

export async function load(force) {             // раз в 10 с достаточно: черновики появляются по ходу работы агента
  if (!force && Date.now() - at < 10000) return list;
  try { list = (await api("/api/drafts")).drafts || []; at = Date.now(); } catch (e) { /* нет прав или сети — нет карточек */ }
  return list;
}

const chatName = (w) => { const s = w && sessions.find((x) => x.id === w); return s ? s.title || s.name : ""; };

export function cards(items = list) {
  return items.map((d) => `<div class="s-yc drf" data-drf="${esc(d.svc)}:${esc(d.id)}">${ic("warn")}<div class="t">
      <b>${esc(svcName(d.svc))}</b><small>${esc(d.summary || d.action)}</small>${chatName(d.w) ? `<small class="from">из чата «${esc(chatName(d.w))}»</small>` : ""}</div>
      <div class="scn-opts"><button class="scn-opt yes" type="button" data-drf-yes>Да</button><button class="scn-opt" type="button" data-drf-edit>Изменить</button><button class="scn-opt" type="button" data-drf-no>Нет</button></div></div>`).join("");
}

// Один обработчик на контейнер: кнопки карточек внутри него. ``after`` — перерисовать список после решения.
export function bind(root, after) {
  if (!root || root.dataset.drfBound) return;
  root.dataset.drfBound = "1";
  root.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-drf-yes], [data-drf-edit], [data-drf-no]"), card = b?.closest("[data-drf]");
    if (!b || !card || busy) return;
    const [svc, id] = card.dataset.drf.split(":"), d = list.find((x) => x.id === id && x.svc === svc);
    if (!d) return;
    busy = true; card.querySelectorAll("button").forEach((x) => (x.disabled = true));
    try {
      if (b.hasAttribute("data-drf-yes")) await yes(d);
      else if (b.hasAttribute("data-drf-edit")) await edit(d);
      else { await api("/api/drafts/no", { svc, id }); toast("Убрал: агент это делать не будет", 3000); }
      list = list.filter((x) => x !== d);
    } catch (err) {
      toast("Не вышло: " + err.message, 4500); card.querySelectorAll("button").forEach((x) => (x.disabled = false));
    } finally { busy = false; after?.(); }
  });
}

async function yes(d) {
  haptic("impactOccurred", "medium");
  await api("/api/drafts/yes", { svc: d.svc, id: d.id });
  if (!d.w) return toast(`Подтверждено. Скажите агенту: «выполни черновик ${d.id}»`, 6000);
  await api("/api/send", { w: d.w, text: `Да — черновик ${d.id} (${svcName(d.svc)}: ${d.summary || d.action}) подтверждён в пульте. Выполни его.` });
  toast("Подтверждено — агент выполнит", 3000);
}

async function edit(d) {
  await api("/api/drafts/no", { svc: d.svc, id: d.id });
  const text = `Черновик «${(d.summary || d.action).slice(0, 200)}» (${svcName(d.svc)}) не отправляю. Исправь: `;
  if (!d.w || !sessions.some((x) => x.id === d.w)) {
    try { await navigator.clipboard.writeText(text); } catch (e) { /* без буфера — только подсказка */ }
    return toast("Черновик снят. Напишите агенту, что исправить (начало ответа — в буфере)", 6000);
  }
  await openSession(d.w);
  const inp = $(SIM?.on ? "sInput" : "input");
  if (inp) { inp.value = text; inp.focus(); inp.setSelectionRange(text.length, text.length); inp.dispatchEvent(new Event("input")); }
}
