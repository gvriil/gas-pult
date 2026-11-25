"""Простой режим: «Подключить почту или мессенджер» (штаб 25.11, вариант А). Владельцу — мессенджеры сразу; человеку
пространства — «Попросить администратора» (задача через отзыв); чужие пароли не храним."""
import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "js/sconnect.js").read_text(encoding="utf-8")


def test_settings_item_and_part():
    assert "'data-conn=\"1\"', T(\"s.conn\")" in INDEX and 'part("sconnect").then((m) => m.open())' in INDEX


def test_owner_messengers_others_ask_admin():
    assert '(await part("messengers")).section(' in JS and 'api("/api/feedback"' in JS and "FOCUS ?" in JS
    for lang in ("ru", "en"):
        d = json.loads((WEB / f"i18n/{lang}.json").read_text(encoding="utf-8"))
        assert all(k in d for k in ("s.conn", "s.conn.admin", "s.conn.ask", "s.conn.asked"))
        assert "владел" not in d["s.conn.admin"].lower()                    # человеку — «администратор пространства»
