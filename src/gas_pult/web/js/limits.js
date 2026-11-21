// Лимиты расхода — форма (вынесено из ядра 21.11: место ядра для правок интерфейса).
export async function open() {
  let cur = { limits: costInfo?.limits || {} };
  try { cur = await api("/api/cost/limits"); } catch (e) { /* покажем то, что знаем */ }
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("settings.limits");
  const v = (x) => x == null ? "" : String(x);
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Лимиты расхода</h3>
    <div class="field" style="margin:4px 16px 10px"><label for="limS">На одну сессию, $</label><input id="limS" inputmode="decimal" autocomplete="off" placeholder="выключен" value="${esc(v(cur.limits.session))}"></div>
    <div class="field" style="margin:0 16px 0"><label for="limD">На день по вашей учётке, $</label><input id="limD" inputmode="decimal" autocomplete="off" placeholder="выключен" value="${esc(v(cur.limits.day))}"></div>
    <p class="note" id="limErr" style="margin:8px 16px 0">Пусто или 0 — без лимита. Превышение: Claude останавливается, сообщения в сессию не уходят, пока вы не решите — в боте или здесь.</p>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="limOk">Сохранить</button></div></div>`;
  document.body.append(bg);
  $("limOk").onclick = async () => {
    try { const r = await api("/api/cost/limits", { session: $("limS").value.trim(), day: $("limD").value.trim() });
          if (costInfo) costInfo.limits = r.limits; bg.remove(); toast("Лимиты сохранены"); haptic("notificationOccurred", "success"); refresh(); }
    catch (e) { $("limErr").textContent = e.message; $("limErr").style.color = "var(--status-danger)"; }
  };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
}
