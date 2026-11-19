// Удобства фокус-ссылки (владелец 19.11: «в фокус-ссылке у сессий должны быть функции переименования,
// тёмный/светлый и все остальные, которые дают удобство»; GAS-13 п.4). Только своё: имя этой сессии, тема и
// размер текста на этом устройстве, «Что здесь умеет». Чужих сессий, терминала и настроек сервера здесь нет.
// Демо-ссылка — только смотреть: пункт меню скрыт, сервер переименование не пускает (403).

export function ease() {
  const s = cur(), mode = store("theme") || "auto";
  const theme = (m) => () => { store("theme", m); applyTheme(); ease(); };
  helpSheet("sheet.focus-ease");
  sheet("Удобства", [
    ...(s && !FOCUS_DEMO() ? [{ label: "Переименовать чат", icon: "edit", sub: s.title || s.name, run: () => renameSession(s) }] : []),
    { label: "Тема: как в системе", on: mode === "auto", run: theme("auto") },
    { label: "Тема: светлая", on: mode === "light", run: theme("light") },
    { label: "Тема: тёмная", on: mode === "dark", run: theme("dark") },
    { label: `Размер текста: ${Math.round(fontPx / FONT.def * 100)} %`, icon: "edit", sub: "A− / A+", run: () => part("zoom").then(() => fontSheet()) },
    ...(s ? [{ label: "Что здесь умеет", icon: "help", sub: "коротко, тур по экрану или прослушать", run: () => part("about").then((m) => m.aboutSession(s.id)) }] : []),
  ]);
}
