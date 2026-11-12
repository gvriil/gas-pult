paintIcons();
applyTheme();
if (tg) { tg.ready(); tg.expand(); try { tg.disableVerticalSwipes?.(); } catch (e) {} tg.BackButton.onClick(back); tg.onEvent?.("themeChanged", applyTheme); tg.onEvent?.("viewportChanged", fitViewport); }
fitViewport();
window.visualViewport?.addEventListener("resize", fitViewport);
window.visualViewport?.addEventListener("scroll", fitViewport);
addEventListener("resize", fitViewport);
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", applyTheme);
wideMQ.addEventListener?.("change", () => { show(view); refresh(); });
termWrap = store("termWrap") === "1";
if (DEMO) $("demoBar").hidden = false;
dictReady.then(paintLoginLang);
dictReady.then(agoTick);                              // «изменена N назад» — тексты из словаря
if (DEMO && params.get("view") === "login") showLogin(); else if (FOCUS) focusStart(); else start();
