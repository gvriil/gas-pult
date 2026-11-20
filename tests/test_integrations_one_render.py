"""Владелец 20.11: «интеграции: сначала вываливаются модели, потом пропадают, появляются другие вещи». Экран рисуется
один раз: «Загружаю…» → весь список (сервисы, календари, модели, запасные, голос) после всех запросов."""
from pathlib import Path

INDEX = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")


def test_load_mcp_waits_for_everything_then_renders_once():
    a = INDEX.index("async function loadMcp(fresh) {")
    body = INDEX[a:INDEX.index("\nfunction renderModels()", a)]
    assert body.index("await Promise.all(") < body.index("renderMcp()") < body.index("renderModels()")
    assert 'part("calkeys").then((x) => x.calendarsSection())' in body          # «Календари» — в той же отрисовке
    assert body.count("box.innerHTML = ") == 2                                   # «загружаю» и итог — два состояния
