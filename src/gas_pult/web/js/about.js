// «Что здесь умеет» в меню сессии (владелец 19.11: «у каждой сессии возможность посмотреть тур или сразу прослушать
// и узнать о функционале — что где как чем пользоваться»). Текст — из карты помощника (help/screens.toml, экран
// «session.chat»): зачем экран и 3 шага. «Показать на экране» — тур пульта по тому, что видно сейчас (startTour);
// «Прослушать» — тот же текст голосом с сервера (/api/tts/about, до ~60 с). Часть грузится по требованию: part("about").

const SCREEN = "session.chat";
let audio = null;

async function mapScreen(id) {
  const m = await (await fetch("/help-map.json", { credentials: "same-origin" })).json();
  return m.screens?.[id] || null;
}

export async function aboutSession(id) {
  let s; try { s = await mapScreen(SCREEN); } catch (e) { return toast("Нет связи", 3000); }
  if (!s) return toast("Описания пока нет", 3000);
  const steps = (s.steps || []).map((x, i) => `<li>${esc(x)}</li>`).join("");
  sSheet(hv("sheet.session-about"), "Что здесь умеет", `<p class="note">${esc(s.purpose || "")}</p>
    <ol class="note" style="padding-left:20px;margin:6px 0">${steps}</ol>
    <div class="scn-opts">${sChip(true, 'data-ab="tour"', "Показать на экране", ic("spark"))}${sChip(false, 'data-ab="say"', "Прослушать", ic("play"))}</div>
    <div id="abOut"></div>`, async (b, bg) => {
    if (b.dataset.ab === "tour") {
      bg.remove();
      if (current !== id) await openSession(id);
      return startTour(tourKind(), true);                       // только то, что на этом экране
    }
    if (b.dataset.ab !== "say") return;
    if (audio && !audio.paused) { audio.pause(); audio = null; b.lastChild.textContent = "Прослушать"; return; }
    $("abOut").innerHTML = `<div class="result wait">${ic("wait")}<span>Готовлю голос…</span></div>`;
    try {
      const blob = await api("/api/tts/about?screen=" + encodeURIComponent(SCREEN));
      audio = new Audio(URL.createObjectURL(blob)); $("abOut").innerHTML = "";
      b.lastChild.textContent = "Остановить"; audio.onended = () => { b.lastChild.textContent = "Прослушать"; };
      await audio.play();
    } catch (e) { $("abOut").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; }
  });
}
