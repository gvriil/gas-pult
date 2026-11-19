// «Анкеты клиентов» (решение 0010; владелец 19.11: «опросник клиенту — HTML-анкета на нашей ссылке… прошёл — мы
// данные собрали и взяли в работу»). Владелец: список личных ссылок (кому, какая анкета, сколько ответов, отправлена
// ли), ответы текстом вопросов, новая ссылка — выбрать анкету, вписать клиента, скопировать адрес. Код ссылки
// показывается один раз — при создании.

const day = (ts) => new Date(ts * 1000).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });

export async function open() {
  let d; try { d = await api("/api/q/list"); } catch (e) { return toast(e.message, 4000); }
  helpSheet("sheet.forms");
  sheet("Анкеты клиентов", [
    { label: "Новая ссылка на анкету", icon: "plus", sub: "клиент заполнит по ссылке, без входа", run: () => newLink(d.forms) },
    ...(d.links.length ? [{ head: "Ссылки" }] : [{ info: true, icon: "help", label: "Ссылок пока нет", sub: "создайте первую — клиенту придёт адрес, ответы — сюда и в бот" }]),
    ...d.links.map((l) => ({ label: l.client, icon: l.sent ? "check" : "wait",
      sub: `${d.forms.find((f) => f.id === l.form)?.title || l.form} · ${l.sent ? "отправлена " + day(l.sent) : "ответов " + l.answered + " · до " + day(l.exp)}`,
      run: () => answers(l.id) })),
  ]);
}

function newLink(forms) {
  if (!forms.length) return toast("Анкет нет: положите файл анкеты в папку данных пульта forms/", 5000);
  sheet("Какая анкета?", forms.map((f) => ({ label: f.title, icon: "file", run: () => askClient(f) })));
}

function askClient(f) {
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.forms");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Для кого анкета?</h3>
    <div class="field" style="margin:4px 16px 0"><input id="qClient" maxlength="80" autocomplete="off" placeholder="Имя клиента или компании"></div>
    <p class="note" style="margin:6px 16px 0">«${esc(f.title)}» · ссылка действует 14 дней, ответы сохраняются по ходу</p>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="qOk">Создать ссылку</button></div></div>`;
  document.body.append(bg);
  const inp = bg.querySelector("#qClient"); inp.focus();
  const go = async () => {
    const client = inp.value.trim(); if (!client) return inp.focus();
    try {
      const r = await api("/api/q/new", { form: f.id, client });
      bg.remove(); const url = location.origin + r.path;
      sheet("Ссылка для «" + client + "»", [
        { info: true, icon: "ext", label: url, sub: "покажу один раз — скопируйте и отправьте клиенту" },
        { label: "Скопировать ссылку", icon: "copy", run: () => copyText(url, "Ссылка скопирована") },
        { label: "Открыть анкету", icon: "ext", run: () => openUrl(url) }]);
    } catch (e) { toast(e.message, 4500); }
  };
  bg.querySelector("#qOk").onclick = go;
  inp.onkeydown = (e) => { if (e.key === "Enter") go(); if (e.key === "Escape") bg.remove(); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
}

async function answers(id) {
  let d; try { d = await api("/api/q/answers?id=" + encodeURIComponent(id)); } catch (e) { return toast(e.message, 4000); }
  sheet(`${d.client} · ${d.sent ? "отправлена " + day(d.sent) : "ещё заполняет"}`, [
    ...d.rows.map((r) => ({ info: true, icon: r.a === "—" ? "x" : "check", label: r.q, sub: r.a })),
    ...(d.profile ? [{ label: "Скопировать описание клиента (JSON)", icon: "copy", sub: "для настройки админки и сканера",
      run: () => copyText(JSON.stringify(d.profile, null, 1), "Описание скопировано") }] : []),
  ]);
}
