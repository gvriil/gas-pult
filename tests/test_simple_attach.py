"""Отчёт «два нажатия» 25.11: скрепка в простом режиме (фото или файл — 2 нажатия) и «Подключить почту или
мессенджер» первым пунктом настроек. Поведение в браузере проверено Playwright в PR."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "js/sattach.js").read_text(encoding="utf-8")
SET = (WEB / "js/settings.js").read_text(encoding="utf-8")


def test_simple_attach_part():
    assert 'if (meta?.role !== "viewer") part("sattach").then((m) => m.init())' in INDEX
    assert 'b.id = "sPlus"' in JS and '"Файл из панели: " + path' in JS and 'api("/api/send"' in JS
    assert "if (SIM.ask) return" in JS and 'w.startsWith("t:")' in JS


def test_connect_first_in_settings():
    assert 'label: "Подключить почту или мессенджер"' in SET and 'go("go:integrations")' in SET
    assert "...quick()," in SET and "[...quick(), ...gs[0].items]" in SET
