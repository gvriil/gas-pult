// Свой порядок строк панели перетаскиванием (владелец 20.11: «внутри закреплённых, проектов, чатов — двигать между
// собой, ставить приоритет»). Мышь: нажали на строку и повели дальше 6 px — строка едет за курсором. Телефон: долгое
// нажатие открывает меню; повели пальцем — меню закрывается, строка едет за пальцем. Двигаем только внутри своей
// группы (data-og="группа|ключ"); отпустили — порядок группы уходит на сервер (saveOrder в ядре).

const grpOf = (row) => row.dataset.og.split("|")[0];

export function arm(e, row) {                          // мышь: ждём сдвига, иначе это обычный щелчок
  const y0 = e.clientY, x0 = e.clientX;
  const move = (ev) => { if (Math.hypot(ev.clientX - x0, ev.clientY - y0) > 6) { off(); drag(ev, row); } };
  const off = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", off); };
  addEventListener("pointermove", move); addEventListener("pointerup", off);
}

export function drag(e, row) {
  if (!row?.isConnected || NAV.drag) return;
  const grp = grpOf(row), list = $("navList");
  NAV.drag = true; NAV.held = true;                   // щелчок после отпускания — не открывать чат
  row.classList.add("dragging"); haptic("impactOccurred", "light");
  let grab = e.clientY - row.getBoundingClientRect().top;
  const place = (y) => {
    const rows = [...list.querySelectorAll(".nrow[data-og]")].filter((r) => r !== row && grpOf(r) === grp && !r.classList.contains("sub") === !row.classList.contains("sub"));
    const before = rows.find((r) => { const b = r.getBoundingClientRect(); return y < b.top + b.height / 2; });
    const tail = (r) => { let n = r; while (n.nextElementSibling?.classList.contains("sub") && !row.classList.contains("sub")) n = n.nextElementSibling; return n; };
    if (before) { if (before.previousElementSibling !== row) list.insertBefore(row, before); }
    else if (rows.length) { const last = tail(rows[rows.length - 1]); if (last.nextElementSibling !== row) last.after(row); }
    row.style.transform = ""; const top = row.getBoundingClientRect().top;   // своё место без сдвига
    row.style.transform = `translateY(${y - grab - top}px)`;
  };
  const move = (ev) => { ev.preventDefault?.(); place(ev.clientY); autoScroll(ev.clientY); };
  const autoScroll = (y) => { const b = list.getBoundingClientRect(); if (y < b.top + 40) list.scrollTop -= 8; else if (y > b.bottom - 40) list.scrollTop += 8; };
  const end = () => {
    removeEventListener("pointermove", move); removeEventListener("pointerup", end); removeEventListener("pointercancel", end);
    row.classList.remove("dragging"); row.style.transform = "";
    const keys = [...list.querySelectorAll(".nrow[data-og]")].filter((r) => grpOf(r) === grp).map((r) => r.dataset.og.slice(grp.length + 1));
    NAV.drag = false; setTimeout(() => { NAV.held = false; }, 0);
    saveOrder(grp, keys);
  };
  addEventListener("pointermove", move, { passive: false }); addEventListener("pointerup", end); addEventListener("pointercancel", end);
  place(e.clientY);
}
