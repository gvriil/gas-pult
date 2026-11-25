"""Тур «Ладеи» для простого режима (владелец 25.11 через штаб): одно нажатие «Показать тур», не больше пяти шагов,
последний — «На экран «Домой»» с картинкой для iPhone и Android, пропуск, если уже установлено; демо — без списка
чатов. Проверка по исходникам; вживую тур проходит браузер (снимки — в PR)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
TOUR = (WEB / "js" / "ladtour.js").read_text(encoding="utf-8")
DEMO = (WEB / "js" / "demo.js").read_text(encoding="utf-8")


def test_at_most_five_steps_and_home_last():
    steps = TOUR[TOUR.index("const STEPS = ["):TOUR.index("];", TOUR.index("const STEPS = ["))]
    assert len(re.findall(r"\{ (?:sel|home):", steps)) <= 5
    assert steps.rstrip().endswith("},") and "home: true" in steps.split("{ sel:")[-1]
    assert "Добавьте Ладею на экран «Домой»" in TOUR and "Add Ladeya to your Home Screen" in TOUR


def test_home_step_both_phones_and_skip_when_installed():
    assert "Поделиться" in TOUR and "На экран «Домой»" in TOUR and "Установить и создать ярлык" in TOUR
    assert '"(display-mode: standalone)"' in TOUR and "navigator.standalone" in TOUR
    assert "s.home ? !installed()" in TOUR
    assert '<img src="/icon-192.png"' in TOUR          # значок — из ladeya-app-icon.svg (tools/brand_images.py)


def test_demo_one_tap_and_no_chat_list():
    assert 'part("ladtour").then((m) => m.start())' in DEMO and 'id = "sTourBtn"' in DEMO
    assert "body.biz-demo #simple #sWho { pointer-events: none; }" in DEMO
    assert 'addEventListener("beforeinstallprompt"' in DEMO


def test_no_external_scripts_and_no_blue():
    assert "cdnjs" not in TOUR and "http" not in TOUR.replace("//", "")
    assert not re.search(r"#(2563EB|4285F4|60A5FA)", TOUR, re.I)


INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def test_simple_mode_help_and_first_entry_offer():
    """Штаб 25.11: «Показать тур» в «?» простого режима (2 нажатия) и одно предложение при первом входе — карточкой,
    не модальным окном; выбор помнится на сервере (вид simple) и на устройстве."""
    assert 'SIM.on ? part("ladtour").then((m) => m.start()) : startTour(tourKind(), true)' in INDEX
    assert 'if (!DEMO) afterPaint(() => part("ladtour").then((m) => m.offer())' in INDEX
    assert 'api("/api/tour", { tour: "simple", state })' in TOUR and 'store(OFFER_KEY, state)' in TOUR
    assert 'aria-modal' not in TOUR.split("export async function offer")[1]          # карточка в ленте, не модальное
    assert 'body.biz-demo .hgo button[data-go="go:simple.agents"] { display: none; }' in DEMO


def test_server_keeps_simple_tour(tmp_path):
    from gas_pult import people
    p = people.People(tmp_path / "people.json", [1])
    p.add(2, "member", "Иван")
    p.set_tour(2, "simple", "dismissed")
    assert p.tour(2)["simple"] == "dismissed" and p.tour(1)["simple"] is None
