"""Модуль «Входящие ЭДО» (acc-edo): в каталоге бухгалтеров, интеграции операторов — только чтение и необязательные,
подписание КЭП — только человек (решение «Да / Нет»), сверка с первичкой acc-primary тем же форматом, пример
выдуманный. Живой tmux и настоящий claude не нужны."""

import re
from pathlib import Path

import pytest

from gas_pult import modules

MID = "acc-edo"


@pytest.fixture(autouse=True)
def own_config(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def m() -> dict:
    errors = []
    by = {x["id"]: x for x in modules.catalog(errors)}
    assert errors == []
    return by[MID]


def test_in_catalog_with_accountants(m):
    assert m["industry"] == modules.get("acc-primary")["industry"] == "Бухгалтеры и юристы на аутсорсе"
    assert "docs" in m["sections"] and [u["id"] for u in m["uses"]] == ["documents"]
    assert {"edo-intake", "edo-match", "edo-to-1c", "requisites-check"} <= set(m["skills"])
    assert {s["kind"] for s in m["data_sources"]} == {"official_api", "client_export"}
    assert [s["days"] for s in m["schedule"]] == [[1, 2, 3, 4, 5]] * 2
    assert "{{" not in m["description"] + m["start"] + "".join(s["prompt"] for s in m["schedule"])


def test_operator_api_read_only_and_optional(m):
    ids = {i["id"] for i in m["integrations"]}
    assert {"diadoc", "sbis", "onec"} <= ids
    for i in m["integrations"]:
        assert i["optional"], i["id"]                       # без API модуль работает от выгрузки в inbox/
        assert "только чтени" in (i["title"] + i["how"]).lower(), i["id"]
        if i["id"] != "onec":
            assert "подписания и отправки в сервере нет" in i["how"], i["id"]


def test_signing_only_by_human(m):
    sign = [d for d in m["decisions"] if "КЭП" in d["question"]]
    assert len(sign) == 1 and sign[0]["options"] == ["Да", "Нет"] and "не подписывает" in sign[0]["when"]
    text = modules.claude_md(m)
    assert "AskUserQuestion" in text and "{{" not in text
    never = text.split("## Нельзя никогда", 1)[1]
    assert "Подписывать документы" in never and "отправлять" in never and "кроме чтения" in never
    assert "агент сам не подписывает" in sign[0]["when"]


def test_matches_acc_primary_format(m):
    """Сверка читает реестр соседнего acc-primary (путь — в settings), пример — того же формата, файл для 1С — тот же
    CSV, что у acc-primary."""
    assert m["settings"]["primary"] == "../acc-primary/registry"
    readme = (modules.builtin_dir() / "acc-primary" / "registry" / "README.md").read_text(encoding="utf-8")
    cols = re.search(r"\.csv`: ([^\n]+)\.", readme).group(1).split(", ")
    ex = Path(m["path"]) / m["settings"]["primary_example"]
    files = list(ex.rglob("*.csv"))
    assert files and all(f.read_text(encoding="utf-8").splitlines()[0].split(",") == cols for f in files)
    assert ", ".join(cols) in (Path(m["path"]) / "CLAUDE.md").read_text(encoding="utf-8")


def test_example_has_no_real_ids_keys_or_addresses(m):
    digits = re.compile(r"(?<![\d-])\d{10,20}(?![\d-])")               # ИНН, счета — только нули
    email = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
    ip = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b")
    url = re.compile(r"https?://\S+")
    secret = re.compile(r"(?i)(token|api[_-]?key|secret|password|пароль)\s*[:=]\s*\S+|-----BEGIN|\bsk-[A-Za-z0-9]")
    for f in Path(m["path"]).rglob("*"):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        assert all(set(x) == {"0"} for x in digits.findall(text)), f
        assert all(x.group(0).endswith("@example.com") for x in email.finditer(text)), f
        assert not ip.search(text) and not url.search(text) and not secret.search(text), f
        assert all(set(x) == {"0"} for x in re.findall(r'(?:ИНН\w*|КПП)="(\d+)"', text)), f   # и КПП (9 цифр)


def test_create_workspace(m, tmp_path):
    p = modules.create(MID, tmp_path / "projects")
    text = (p / "CLAUDE.md").read_text(encoding="utf-8")
    assert "{{" not in text and "../acc-primary/registry" in text and "## Общий блок: Документы" in text
    for s in ("edo-intake", "edo-match", "edo-to-1c", "document-draft"):
        assert (p / ".claude" / "skills" / s / "SKILL.md").is_file()
    assert sorted(x.name for x in (p / "inbox" / "1").glob("*.xml")) == ["akt-7-example.xml", "upd-12-example.xml"]
    assert not (p / "module.toml").exists() and modules.mark_of(p)["id"] == MID
