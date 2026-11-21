// «Подробнее» о чате — телеметрия: модель, контекст, расход, папка, ветка, лимиты. Видна в режиме разработчика
// (Gemini 21.11, №1 [У]); вынесено из ядра.
export function open(id) {
  const s = sessions.find((x) => x.id === id); if (!s) return;
  const RAW = { idle: "свободен", busy: "работает", dialog: "ждёт ответа", sleep: "спит", stopped: "спит — проснётся от сообщения" };
  const row = (label, sub) => sub ? [{ info: true, label, sub: String(sub) }] : [];
  helpSheet("sheet.session");
  sheet("Подробнее: " + dn(s), [
    ...row("Состояние", RAW[s.status] || s.status), ...row("Модель", [s.model, s.effort && "усилия " + (EFFORT_RU[s.effort] || s.effort)].filter(Boolean).join(" · ")),
    ...row("Поставщик", provName(s)), ...row("Контекст", ctxUsed(s) == null ? "" : ctxUsed(s) + " %"),
    ...row("Расход", s.cost?.total ? (s.cost.usd == null ? tok(s.cost.total) + " токенов" : usd(s.cost.usd)) : ""),
    ...row("Папка", s.path), ...row("Ветка", s.branch && s.branch !== "HEAD" ? s.branch : ""),
    ...(s.repos?.length && canRepos(s) ? [{ label: "Репозитории", icon: "folder", sub: s.repos.map((r) => r.name).join(", ") + " — подключить или отключить", run: () => repoSheet(id) }]
      : row("Репозитории", s.repos?.map((r) => r.name).join(", "))), ...row("В чате бота", s.active ? "активная — ответы бота от этого чата" : ""),
    ...(s.harness && s.harness !== "claude" ? row("Токены и расход", usageLine(s.usage).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()) : []),
    ...(meta?.role === "owner" && (s.harness || "claude") === "claude" && limitsInfo?.limits ? row("Лимиты подписки", limitsLine(limitsInfo).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()) : []),
    { label: "Что здесь умеет", icon: "help", sub: "коротко, тур по экрану или прослушать", run: () => part("about").then((m) => m.aboutSession(id)) },
    ...(meta?.role !== "viewer" && !FOCUS && !s.space && !document.body.classList.contains("nocap-dev_terminal") ? [{ label: "Экран терминала", icon: "term", run: () => { openSession(id); setTab("screen"); } }] : []),
  ]);
}
