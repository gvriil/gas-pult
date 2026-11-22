"""Gemini 21.11, топ-15 №1 и №13 (пометка [У] — скрыть вне режима разработчика): «Подробнее» (телеметрия), «изменена
N назад» в шапке и у поля, метки «все поставщики», экран «Поставщики»; «Убрать» — компактная «Отключить» в строке."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
PAGE = (WEB / "index.html").read_text(encoding="utf-8")


def test_details_and_ago_only_for_developer():
    assert PAGE.count('...(dev() ? [{ label: "Показать подробности", icon: "eye"') == 2
    assert 'const ag = dev() ? agoSpan(s, true) : "";' in PAGE


def test_integrations_quiet_for_user():
    assert '${dev() ? `<small class="chip ok">${esc(T("int.any.chip"))}</small>` : ""}' in PAGE
    assert '<button class="btn danger sm rm-inline" data-rm="${srv.indexOf(s)}">Отключить</button>' in PAGE
    assert ">Убрать</button>" not in PAGE.split("function renderMcp")[1].split("\nfunction ")[0]
    st = (WEB / "js/settings.js").read_text(encoding="utf-8")
    assert 'meta?.role === "owner" && dev("dev_models_mcp") ? [{ label: T("st.title")' in st


def test_home_quiet_for_user():                                         # №4
    assert '${dev() ? `<span class="chip s-running"><b>${n("busy")}</b> работают</span>' in PAGE
    assert '${isNew(s) && dev() ? \'<span class="chip new">новый ответ</span>\' : ""}' in PAGE
    assert '${dev() ? schedChip(s) : ""}' in PAGE and '${isNew(s) ? " unread" : ""}' in PAGE
    assert "body.split .card .reply { width: fit-content;" in PAGE


def test_chat_menu_short_for_user():                                    # №10
    assert "sheet(dn(s), shortMenu([" in PAGE
    assert '...(s.space || !dev() || FOCUS ? [] : [{ label: "Сделать активной",'   # по ссылке /api/active — 403 in PAGE
    assert '...(canRepos(s) && dev() ? [{ label: "Подключить репозитории",' in PAGE
    assert "return dev() ? out : out.map(({ sub, ...x }) => x);" in PAGE
    assert "it.sep ? '<hr class=\"ssep\">'" in PAGE
