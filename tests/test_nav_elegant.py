"""Владелец 20.11: новый чат прямо в проекте («+» у проекта) и мягкое выделение строк панели — без резких цветов."""
from pathlib import Path

INDEX = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")


def test_plus_on_project_opens_new_chat_in_it():
    assert 'data-nnew aria-label="Новый чат в проекте"' in INDEX
    assert 'if (e.target.closest("[data-nnew]")) { navOpen(false); return newChat(row.dataset.np); }' in INDEX
    assert "@media (hover: none) { .nrow .nadd { display: grid;" in INDEX           # на телефоне «+» виден всегда
    assert "Начать чат в проекте" not in INDEX


def test_soft_hover_and_selection():
    assert "--row-hv: 5%;" in INDEX and ':root[data-theme="dark"] { --row-hv: 7%;' in INDEX
    assert ".nrow { transition: background-color .12s ease; }" in INDEX
    assert ".nrow.on { background: var(--accent-soft)" not in INDEX                # без резкого акцентного цвета
    assert "#navList .nrow:focus-visible { outline: none; box-shadow: inset 0 0 0 2px var(--border-focus); }" in INDEX
