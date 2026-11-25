// Скрепка в простом режиме (отчёт «два нажатия» 25.11, штаб: «делай»): раньше фото или файл в простом режиме можно
// было только перетащить. Нажатие — выбор файла (на телефоне система сама предложит камеру и галерею), второе
// нажатие — выбрать; файл загружается и сразу уходит агенту вместе с текстом из поля (подпись — по желанию; снимок
// без подписи агент не пропускает). Часть по требованию (#191): ядро не растёт.
let input = null;

async function sendFile(f) {
  const w = SIM.w; if (!w) return toast(T("s.fail.send"), 3500);
  if (SIM.ask) return toast(T("s.answer.wait"), 4000);                          // сначала ответ на вопрос агента
  const t = $("sInput"), note = t.value.trim();
  toast(T("s.attach.up", { n: f.name || "photo" }), 2500);
  try {
    let path;
    if (w.startsWith("t:")) path = (await sfPut(w, f, f.name)).name;            // пространство — его папка
    else {
      await part("upload");
      const g = f.type.startsWith("image/") ? await shrinkImage(f) : f;        // фото — сжать, документ — как есть
      path = (await uploadXhr(`/api/upload?w=${encodeURIComponent(w)}`, g, { "X-File-Name": encodeURIComponent(g.name || "file") }, () => {})).path;
    }
    const text = (note ? note + "\n\n" : "") + "Файл из панели: " + path;
    t.value = ""; sGrow();
    await api("/api/send", { w, text, id: msgId() });
    toast(DEMO ? T("s.attach.demo") : T("s.sent"), 3000); setTimeout(sTick, 800);
  } catch (e) { toast(T("s.attach.fail", { n: f.name || "file", e: e.message }), 4500); }
}

export function init() {
  if ($("sPlus") || !$("sMic")) return;
  input = document.createElement("input"); input.type = "file"; input.hidden = true; input.multiple = true;
  input.onchange = () => { [...input.files].forEach(sendFile); input.value = ""; };
  const b = document.createElement("button");
  b.type = "button"; b.className = "tool"; b.id = "sPlus"; b.innerHTML = ic("attach");
  b.setAttribute("aria-label", T("s.attach")); b.title = T("s.attach");
  b.onclick = () => input.click();
  $("sInput").after(b); b.after(input);
}
