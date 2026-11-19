// Первый разговор (GAS-37; владелец 19.11: «подсказать, что он хочет — бейджики… чтобы сразу кликнуть, и ему тематично
// пошли вопросы»). Бейджики — с сервера (/api/starters: что подключено, роль); нажали — сервер отдаёт текст сценария
// (агент расспросит по одному вопросу с вариантами-кнопками, потом сделает) и пишет замер в журнал событий без текста.

let LIST = null;

export async function paint() {
  const box = $("starters"); if (!box) return;
  try { LIST ??= (await api("/api/starters")).starters || []; } catch (e) { LIST = []; }
  if (!LIST.length || !$("starters")) return;
  $("starters").innerHTML = `<p class="note" style="margin:14px 0 6px">С чего начнём? Нажмите — я расспрошу и сделаю.</p>
    <div class="scn-opts">${LIST.map((x) => sChip(false, `data-starter="${esc(x.id)}"`, x.title)).join("")}</div>`;
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-starter]"); if (!b) return;
  b.disabled = true;
  try {
    const { prompt } = await api("/api/starter", { id: b.dataset.starter, w: current || "" });
    const inp = $("input"); inp.value = prompt; inp.dispatchEvent(new Event("input"));
    await sendText();
  } catch (err) { toast(err.message, 4000); b.disabled = false; }
});
