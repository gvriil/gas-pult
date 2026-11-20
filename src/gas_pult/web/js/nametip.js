// Название чата по смыслу (владелец 19.11: «если человек быстро начал сессию, по общему смыслу присваивать ей
// название или хотя бы предлагать»). Сервер даёт название по смыслу (projects.title_of: статусы вроде «Ожидание
// формулировки задачи» не считаются). Когда у нового чата оно впервые появилось — плашка «Назвать чат: „…“?
// Да / Изменить»; без ответа за 20 с название закрепляется (своё — автоматика его больше не меняет).

const SEEN = {};                                       // sid → было ли название по смыслу, когда чат увидели впервые
const WAIT = 20000;

export function watch(s) {
  if (!s?.sid || s.title_own || FOCUS_DEMO() || meta?.role === "viewer") return;
  const named = !!s.title && !s.title_status && s.title !== (s.wname || s.name);
  if (!(s.sid in SEEN)) { SEEN[s.sid] = named; return; }    // открыли уже названный чат — не предлагаем
  if (SEEN[s.sid] || !named || store("nt:" + s.sid)) return;
  SEEN[s.sid] = true; store("nt:" + s.sid, "1");
  offer(s);
}

function offer(s) {
  const el = document.createElement("div"); el.className = "toast nametip"; el.setAttribute("role", "status");
  el.innerHTML = `<span>Назвать чат: «${esc(s.title)}»?</span> <button type="button" class="toast-undo" data-nt="yes">Да</button><button type="button" class="toast-undo" data-nt="edit">Изменить</button>`;
  let done = false;
  const put = (title) => { done = true; el.remove(); return api("/api/title", { w: s.id, title }).then(() => refresh()).catch((e) => toast(e.message, 4000)); };
  el.addEventListener("click", (e) => {
    const b = e.target.closest("[data-nt]"); if (!b) return;
    if (b.dataset.nt === "yes") { put(s.title); toast("Чат называется «" + s.title + "»"); }
    else { done = true; el.remove(); renameSession(s); }
  });
  notice(el);
  setTimeout(() => { if (!done && el.isConnected) put(s.title); }, WAIT);
}
