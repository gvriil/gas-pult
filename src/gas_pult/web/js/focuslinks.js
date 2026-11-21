// «Настройки» → «Фокус-ссылки»: действующие ссылки и карточка ссылки. Вынесено из ядра 21.11 (место ядра).
export async function open() {
  let d; try { d = await api("/api/focus/list"); } catch (e) { return toast(e.message, 5000); }
  const when = (t) => new Date(t * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  helpSheet("settings.focus");
  for (const x of d.links) if (!x.proj) x.name = sessions.find((y) => y.id === x.w)?.name || x.name || "Чат";   // не имя окна (19.11)
  sheet("Фокус-ссылки", d.links.length ? [
    { info: true, icon: "qr", label: "Действующие ссылки", sub: "нажмите — новая ссылка на тот же чат или проект, или отозвать" },
    ...d.links.map((x) => ({ label: (x.mode === "demo" ? "Демо · " : "") + (x.proj ? "Проект «" + x.name + "»" : x.name) + (x.space ? " · " + x.space : ""), icon: x.mode === "demo" ? "eye" : x.proj ? "folder" : "chat",
      sub: (x.mode === "demo" ? (x.devices ? `${x.devices} ${plural(x.devices, ["устройство", "устройства", "устройств"])} · последнее ${when(x.opened)}` : "ещё не открыта")
        : x.opened ? `открыта ${when(x.opened)} · ${x.device || "устройство"}` : "ещё не открыта") + ` · до ${when(x.exp)}`,
      run: () => card(x) }))]
    : [{ info: true, icon: "qr", label: "Фокус-ссылок нет", sub: "выпустить — меню сессии → «Фокус-ссылка»" }]);
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
    { sep: true },
    { label: "Отозвать эту ссылку", icon: "x", danger: true, sub: "устройство сразу потеряет доступ, чат продолжит работать",
      run: () => confirmDanger(`Отозвать ссылку на «${x.name}»? Устройство сразу потеряет доступ, ${x.proj ? "чаты продолжат" : "чат продолжит"} работать.`,
        async () => { try { await api("/api/focus/revoke", { id: x.id }); toast("Ссылка отозвана"); open(); } catch (e) { toast(e.message, 5000); } }) },
  ]);
}
