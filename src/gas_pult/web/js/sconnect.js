// «Подключить почту или мессенджер» в простом режиме (отчёт «два нажатия» 25.11; штаб — вариант А). Настройки →
// этот пункт: у владельца пульта — сразу мессенджеры (их форма — js/messengers.js), почта — в полных «Подключениях».
// У человека пространства подключения ставит администратор пространства: кнопка «Попросить администратора» — задача
// ему (отзыв, feedback.py). Чужие пароли не храним; ресурсы владельца человеку не называем. Часть по требованию (#191).
export async function open() {
  const owner = meta?.role === "owner" && !meta?.space && !FOCUS;
  if (owner) {
    const bg = sSheet("simple.settings", T("s.conn.title"), `<p class="s-lbl">${esc(T("s.conn.msg"))}</p><div id="sConnMsg"></div>
      <p class="s-lbl">${esc(T("s.conn.mail"))}</p><p class="note">${esc(T("s.conn.mail.owner"))}</p>`);
    try { (await part("messengers")).section(bg.querySelector("#sConnMsg")); } catch (e) {}
    return;
  }
  sSheet("simple.settings", T("s.conn.title"), `<p class="note">${esc(T("s.conn.admin"))}</p>
    ${FOCUS ? "" : `<div class="scn-opts"><button class="scn-opt" type="button" data-ask="1">${ic("mail")}<span>${esc(T("s.conn.ask"))}</span></button></div>`}`,
  async (b, bg) => {
    if (!b.dataset.ask) return;
    b.disabled = true;
    try {
      await api("/api/feedback", { text: T("s.conn.ask.text"), screen: "простой режим · подключения" });
      bg.remove(); toast(T("s.conn.asked"), 3500);
    } catch (e) { b.disabled = false; toast(e.message, 4000); }
  });
}
