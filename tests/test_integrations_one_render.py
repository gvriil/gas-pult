"""Владелец 20.11: «интеграции: сначала вываливаются модели, потом пропадают, появляются другие вещи». С 24.11
(каталог по разделам, UI-обзор: окно открывалось 8–10 с): сразу — каталог из кэша или скелетон, модели — раздел того же
каталога (не отдельный блок, который появляется и пропадает), статусы — тем же renderMcp на том же месте, поиск
сохраняется; календари дорисовываются в свой блок."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
CONN = (WEB / "js/connections.js").read_text(encoding="utf-8")


def test_catalog_first_then_statuses_in_place():
    a = INDEX.index("async function loadMcp(fresh) {")
    body = INDEX[a:INDEX.index("\n}\n", a)]
    first = body.index("CONN.cached()")
    assert first < body.index("CONN.skeleton()") < body.index('q("/api/mcp?catalog=1")') < body.index("full.then(")
    assert "renderMcp(had)" in body                      # статусы — та же отрисовка, поиск не сбрасывается
    assert 'id="modelsBox"' not in body and 'id="modelsBox" data-tour="models"' in CONN   # модели — раздел каталога
