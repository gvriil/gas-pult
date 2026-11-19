// Первый разговор (GAS-37; владелец 19.11: «подсказать, что он хочет — бейджики… чтобы сразу кликнуть, и ему тематично
// пошли вопросы»). Бейджики — с сервера (/api/starters: что подключено, роль); нажали — сервер отдаёт текст сценария
// (агент расспросит по одному вопросу с вариантами-кнопками, потом сделает) и пишет замер в журнал событий без текста.
// Владелец 19.11 (позже): «на пустом чате — спросить, чем человек занимается, и предложить 3–4 небанальных сценария
// под ответ». Ответ — кнопками, запоминается на устройстве («-» — пропустил); «Другое занятие» — спросить снова.

let D = null;
const occ = () => store("occ") || "";
const q = () => (occ() && occ() !== "-" ? "?occ=" + encodeURIComponent(occ()) : "");

export async function paint() {
  if (!$("starters")) return;
  try { D = await api("/api/starters" + q()); } catch (e) { D = { starters: [], occupations: [] }; }
  draw();
}

function draw() {
  const box = $("starters"); if (!box || !D) return;
  if (!occ() && D.occupations?.length) {
    box.innerHTML = `<p class="note" style="margin:14px 0 6px">Чем вы занимаетесь? Подскажу, с чего начать.</p>
      <div class="scn-opts">${D.occupations.map((o) => sChip(false, `data-occ="${esc(o.id)}"`, o.title)).join("")}${sChip(false, 'data-occ="-"', "Пропустить")}</div>`;
    return;
  }
  if (!D.starters?.length) { box.innerHTML = ""; return; }
  box.innerHTML = `<p class="note" style="margin:14px 0 6px">С чего начнём? Нажмите — я расспрошу и сделаю.</p>
    <div class="scn-opts">${D.starters.map((x) => sChip(false, `data-starter="${esc(x.id)}"`, x.title)).join("")}${D.occupations?.length ? sChip(false, "data-occ-reset", D.occ ? "Другое занятие" : "Подобрать под занятие", ic("refresh")) : ""}</div>`;
}

document.addEventListener("click", async (e) => {
  const o = e.target.closest("[data-occ]");
  if (o) { store("occ", o.dataset.occ); return paint(); }
  if (e.target.closest("[data-occ-reset]")) { store("occ", ""); return paint(); }
  const b = e.target.closest("[data-starter]"); if (!b) return;
  b.disabled = true;
  try {
    const { prompt } = await api("/api/starter", { id: b.dataset.starter, w: current || "" });
    const inp = $("input"); inp.value = prompt; inp.dispatchEvent(new Event("input"));
    await sendText();
  } catch (err) { toast(err.message, 4000); b.disabled = false; }
});
