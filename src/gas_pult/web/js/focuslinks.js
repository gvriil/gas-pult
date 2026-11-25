// «Настройки» → «Фокус-ссылки»: действующие ссылки и карточка ссылки. Вынесено из ядра 21.11 (место ядра).
export async function open() {
  let d; try { d = await api("/api/focus/list"); } catch (e) { return toast(e.message, 5000); }
  const when = (t) => new Date(t * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  if (!spacesInfo) await loadSpaces();
  const sl = await part("spacelink");                  // ссылки на пространство (GAS-38): своя строка и «Отозвать»
  helpSheet("settings.focus");
  const add = spacesInfo?.tenants?.length ? [{ label: "Ссылка на пространство", icon: "flask", sub: "полная панель пространства: срок, устройства, права", run: () => sl.form() }] : [];
  const spaceRow = (x) => ({ label: "Пространство «" + x.name + "»", icon: "flask", sub: sl.terms(x, x.devices), run: () => spaceCard(x, sl) });
  // ссылка на протокол встречи (владелец 22.11): только этот протокол; нажатие — открыть протокол или отозвать
  const mtRow = (x) => ({ label: "Протокол «" + x.name + "»", icon: "file", sub: (x.devices ? `${x.devices} ${plural(x.devices, ["устройство", "устройства", "устройств"])} · последнее ${when(x.opened)}` : "ещё не открыта") + ` · до ${when(x.exp)}`,
    run: () => sheet("Протокол «" + x.name + "»", [{ label: "Открыть протокол", icon: "file", run: () => part("meeting").then((m) => m.open(x.mt)) },
      { label: "Отозвать", icon: "x", danger: true, sub: "все устройства сразу потеряют доступ к протоколу",
        run: async () => { try { await api("/api/focus/revoke", { id: x.id }); toast("Ссылка отозвана"); open(); } catch (e) { toast(e.message, 5000); } } }]) });
  for (const x of d.links) if (!x.proj) x.name = sessions.find((y) => y.id === x.w)?.name || x.name || "Чат";   // не имя окна (19.11)
  sheet("Фокус-ссылки", d.links.length ? [
    { info: true, icon: "qr", label: "Действующие ссылки", sub: "нажмите — новая ссылка на тот же чат или проект, или отозвать" },
    ...d.links.map((x) => x.mode === "space" ? spaceRow(x) : x.mode === "meeting" ? mtRow(x) : ({ label: (x.mode === "demo" ? "Демо · " : "") + (x.proj ? "Проект «" + x.name + "»" : x.name) + (x.space ? " · " + x.space : ""), icon: x.mode === "demo" ? "eye" : x.proj ? "folder" : "chat",
      sub: (x.mode === "demo" ? (x.devices ? `${x.devices} ${plural(x.devices, ["устройство", "устройства", "устройств"])} · последнее ${when(x.opened)}` : "ещё не открыта")
        : x.opened ? `открыта ${when(x.opened)} · ${x.device || "устройство"}` : "ещё не открыта") + ` · до ${when(x.exp)}`,
      run: () => card(x) }))].concat(add)
    : [{ info: true, icon: "qr", label: "Фокус-ссылок нет", sub: "выпустить — меню сессии → «Фокус-ссылка»" }, ...add]);
}

// Ссылка на пространство: условия и «Отозвать» одной кнопкой (токен не хранится — скопировать нельзя, только новую)
function spaceCard(x, sl) {
  sheet("Пространство «" + x.name + "»", [
    { info: true, icon: "flask", label: x.space, sub: sl.terms(x, x.devices) },
    { label: "Новая ссылка на это пространство", icon: "qr", run: () => sl.form(x.space) },
    { label: "Отозвать", icon: "x", danger: true, sub: "все устройства сразу потеряют доступ, чаты пространства продолжат работать",
      run: async () => { try { await api("/api/focus/revoke", { id: x.id }); toast("Ссылка отозвана"); open(); } catch (e) { toast(e.message, 5000); } } },
  ]);
}

// Карточка ссылки (штаб 21.11, пункт 5): из фокус-ссылки — ещё одна, на тот же чат, на его проект или на чат проекта;
// значки различают: чат — «чат», проект — папка, демо — глаз
function card(x) {
  const demo = x.mode === "demo" ? "demo" : undefined;
  const chat = !x.proj && sessions.find((y) => y.id === x.w), proj = x.proj || chat?.project || "";
  const pname = projOf(proj)?.name || "";
  const chats = x.proj ? sessions.filter((y) => y.project === x.proj && !y.space) : [];
  sheet(x.proj ? "Проект «" + x.name + "»" : x.name, [
    ...(x.proj ? [{ label: "Новая ссылка на этот проект", icon: "folder", sub: "все чаты проекта", run: () => focusLink(null, x.proj, demo) }]
      : chat ? [{ label: "Новая ссылка на этот чат", icon: "chat", sub: "только этот чат", run: () => focusLink(x.w, null, demo) }] : []),
    ...(!x.proj && proj ? [{ label: "Ссылка на проект «" + pname + "»", icon: "folder", sub: "все чаты проекта", run: () => focusLink(null, proj, demo) }] : []),
    ...(chats.length ? [{ head: "Ссылка на один чат проекта" }, ...chats.map((y) => ({ label: y.title || y.name, icon: "chat", run: () => focusLink(y.id, null, demo) }))] : []),
    ...(x.proj && !demo ? [{ sep: true }, { label: x.auto_adopt ? "Новые окна владельца видны человеку" : "Новые окна владельца скрыты",
      icon: x.auto_adopt ? "eye" : "lock", sub: x.auto_adopt ? "нажмите, чтобы скрывать: человек увидит только чаты, начатые по ссылке"
        : "нажмите, чтобы показывать: окна, которые вы откроете в этой папке, станут видны человеку",
      run: () => (x.auto_adopt ? Promise.resolve(true) : new Promise((ok) => confirmDanger("Новые окна, которые вы открываете в папке «" + x.name
        + "», будут видны человеку по этой ссылке — с перепиской, файлами и тем, что прочитает агент. Показывать?", () => ok(true))))
        .then(async () => { try { await api("/api/focus/auto", { id: x.id, on: !x.auto_adopt }); x.auto_adopt = !x.auto_adopt;
          toast(x.auto_adopt ? "Новые окна будут видны человеку" : "Новые окна скрыты от человека"); card(x); } catch (e) { toast(e.message, 5000); } }) }] : []),
    { sep: true },
    { label: "Отозвать эту ссылку", icon: "x", danger: true, sub: "устройство сразу потеряет доступ, чат продолжит работать",
      run: () => confirmDanger(`Отозвать ссылку на «${x.name}»? Устройство сразу потеряет доступ, ${x.proj ? "чаты продолжат" : "чат продолжит"} работать.`,
        async () => { try { await api("/api/focus/revoke", { id: x.id }); toast("Ссылка отозвана"); open(); } catch (e) { toast(e.message, 5000); } }) },
  ]);
}
