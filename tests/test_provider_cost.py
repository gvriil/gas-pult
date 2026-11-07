"""Цена сессий на моделях не Anthropic (задача 51): Claude Code чужих моделей не знает (``unrecognized_model``) и
считает их по тарифам Anthropic — пульт берёт цену у поставщика. OpenRouter — счёт за каждый ответ
(``/api/v1/generation``, подменён), Z.ai и DeepSeek — оценка по токенам и тарифу из models.py. Без сети."""

import io
import json
import urllib.error
from datetime import date, timedelta

import pytest

from gas_pult import models, openrouter, usage
from gas_pult import space_budget as sb

TODAY = date.today().isoformat()
NOW = f"{TODAY}T12:00:00Z"
GEN = "gen-1794000000-TestGenAaaaaaaaaaaaa1"
GEN2 = "gen-1794000001-TestGenBbbbbbbbbbbbb2"
FAKE_KEY = "sk-or-v1-" + "0" * 8 + "fake"        # поддельный, склейкой — не похож на настоящий


def answer(mid, model, rid="", ts=NOW, cost_usd=None, **u):
    usage_ = {"input_tokens": 1000, "output_tokens": 1000, "cache_creation_input_tokens": 0,
              "cache_read_input_tokens": 0, **u}
    e = {"type": "assistant", "timestamp": ts, "requestId": rid or f"req_{mid}",
         "message": {"id": mid, "model": model, "role": "assistant", "content": [], "usage": usage_}}
    if cost_usd is not None:                       # «цена» Claude Code по тарифам Anthropic — пульт её не берёт
        e["costUSD"] = cost_usd
    return e


def write(f, *entries):
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


class FakeBilling(openrouter.Billing):
    """Счёт OpenRouter без сети и без фонового потока: ответы — из словаря."""

    def __init__(self, tmp_path, costs, key=FAKE_KEY):
        self.calls = []

        def fetch(gen, k):
            self.calls.append((gen, k))
            v = costs.get(gen)
            if v is None:
                raise openrouter.NotYet
            return v
        super().__init__(path=tmp_path / "or-costs.json", key=lambda: key, fetch=fetch, autostart=False)


# ---------- кто поставщик и сколько стоит ----------

def test_provider_of_model():
    assert usage.provider_of("claude-opus-5-5") == "anthropic"
    assert usage.provider_of("deepseek/deepseek-v4-pro-0813") == "openrouter"
    assert usage.provider_of("anthropic/claude-sonnet-5.5") == "openrouter"       # через OpenRouter — его счёт
    assert usage.provider_of("weird", GEN) == "openrouter"
    assert usage.provider_of("glm-5.3-flash") == "zai"
    assert usage.provider_of("deepseek-v4-pro") == "deepseek"
    assert usage.provider_of("GigaChat-2-Max") == "" and usage.provider_of("") == ""


def test_provider_prices_and_estimate():
    assert models.provider_price("zai", "glm-5.3[1m]") == (1.4, 4.4, 0.26)
    assert models.provider_price("zai", "glm-5.3-flash") == (0.15, 0.50, 0.03)     # длинное совпадение раньше
    assert models.provider_price("zai", "glm-5.3-flashx") == (0.37, 1.25, 0.075)
    assert models.provider_price("deepseek", "deepseek-v4-pro") == (1.32, 3.96, 0.044)
    assert models.provider_price("deepseek", "deepseek-chat") == (0.30, 1.20, 0.006)  # старые имена — по Flash
    assert models.provider_price("zai", "gpt-5") is None
    t = {"in": 1_000_000, "out": 1_000_000, "cr": 1_000_000, "cw": 1_000_000}
    assert models.estimate("zai", "glm-5.3", t) == pytest.approx(1.4 + 4.4 + 0.26 + 1.4)   # запись — по вводу
    # DeepSeek: час пик (пн 02:00 UTC) — полная цена, ночь и выходные — вдвое ниже
    assert models.estimate("deepseek", "deepseek-v4-pro", t, "2026-11-09T02:00:00Z") == pytest.approx(
        1.32 + 3.96 + 0.044 + 1.32)
    assert models.estimate("deepseek", "deepseek-v4-pro", t, "2026-11-09T12:00:00Z") == pytest.approx(
        (1.32 + 3.96 + 0.044 + 1.32) / 2)
    assert models.estimate("deepseek", "deepseek-flash", t, "2026-11-07T02:00:00Z") == pytest.approx(
        (0.30 + 1.20 + 0.006 + 0.30) / 2)                                          # суббота — не пик
    assert models.estimate("zai", "unknown-model", t) is None


# ---------- журналы ----------

def test_anthropic_unchanged(tmp_path):
    f = tmp_path / "p" / "s.jsonl"
    write(f, answer("m1", "claude-opus-5-5", cost_usd=99.0))
    pub = usage.public(usage.Meter(tmp_path, billing=FakeBilling(tmp_path, {})).read(f).total)
    assert pub["usd"] == pytest.approx((1000 * 4 + 1000 * 20) / 1e6)              # прайс Anthropic, как раньше
    assert pub["cost_source"] == "anthropic" and pub["pending"] == 0 and not pub["unknown"]


def test_zai_and_deepseek_estimate_ignores_claude_code_cost(tmp_path):
    """Claude Code считает GLM по тарифам Anthropic — не берём её: токены × тариф Z.ai."""
    f = tmp_path / "p" / "s.jsonl"
    write(f, answer("z1", "glm-5.3", cost_usd=0.14, input_tokens=5192, output_tokens=448,
                    cache_read_input_tokens=22144))
    pub = usage.public(usage.Meter(tmp_path, billing=FakeBilling(tmp_path, {})).read(f).total)
    want = (5192 * 1.4 + 448 * 4.4 + 22144 * 0.26) / 1e6
    assert pub["usd"] == pytest.approx(want, abs=1e-4) and pub["cost_source"] == "estimate"
    assert pub["usd"] != pytest.approx(0.14)
    g = tmp_path / "q" / "s.jsonl"
    write(g, answer("d1", "deepseek-v4-pro", ts="2026-11-07T12:00:00Z", cost_usd=1.0,      # суббота — не пик
                    input_tokens=1_000_000, output_tokens=1_000_000))
    pub = usage.public(usage.Meter(tmp_path, billing=FakeBilling(tmp_path, {})).read(g).total)
    assert pub["usd"] == pytest.approx((1.32 + 3.96) / 2) and pub["cost_source"] == "estimate"


def test_openrouter_price_from_provider_bill(tmp_path):
    """Цена ответа OpenRouter — его счёт (total_cost), а не токены: пока счёт не пришёл — «ждёт цены»."""
    bill = FakeBilling(tmp_path, {GEN: 0.0612})
    m = usage.Meter(tmp_path, billing=bill)
    f = tmp_path / "p" / "s.jsonl"
    write(f, answer("msg_TestGenAaaaaaaaaaaaa1", "deepseek/deepseek-v4-pro-0813", rid=GEN, cost_usd=0.02))
    pub = usage.public(m.read(f).total)
    assert pub["usd"] is None and pub["pending"] == 1 and pub["cost_source"] == "provider" and pub["unknown"]
    assert bill.calls == []                                                      # читатель сеть не ждёт
    assert bill.step(now=1e12) == {GEN: 0.0612}
    assert bill.calls == [(GEN, FAKE_KEY)]
    pub = usage.public(m.read(f).total)
    assert pub["usd"] == pytest.approx(0.0612) and pub["pending"] == 0 and not pub["unknown"]
    day = usage.public(m.day(fresh=True))
    assert day["usd"] == pytest.approx(0.0612) and day["cost_source"] == "provider"
    # повтор строки с ростом токенов — цена та же, не удваивается
    write(f, answer("msg_TestGenAaaaaaaaaaaaa1", "deepseek/deepseek-v4-pro-0813", rid=GEN, output_tokens=2000))
    assert usage.public(m.read(f).total)["usd"] == pytest.approx(0.0612)
    # кэш на диске: другой процесс пульта не спрашивает OpenRouter заново
    other = FakeBilling(tmp_path, {})
    assert other.lookup(GEN) == ("provider", pytest.approx(0.0612)) and other.calls == []


def test_openrouter_retry_give_up_and_no_key(tmp_path):
    bill = FakeBilling(tmp_path, {})                                             # счёт так и не появился
    m = usage.Meter(tmp_path, billing=bill)
    f = tmp_path / "p" / "s.jsonl"
    write(f, answer("msg_x", "anthropic/claude-haiku-5.5", rid=GEN2))
    assert usage.public(m.read(f).total)["pending"] == 1
    now = 1e12
    for _ in range(openrouter.Billing.TRIES):
        now += 10_000
        bill.step(now=now)
    pub = usage.public(m.read(f).total)
    assert pub["pending"] == 0 and pub["usd"] is None and pub["unknown"]        # сдались — «цена неизвестна»
    assert len(bill.calls) == openrouter.Billing.TRIES
    nokey = FakeBilling(tmp_path / "n", {GEN: 1.0}, key=None)
    (tmp_path / "n").mkdir()
    assert nokey.lookup(GEN) == ("wait", None)
    assert nokey.step(now=1e12) == {} and nokey.calls == []                     # без ключа — в сеть не ходим


def test_fetch_generation_http(monkeypatch):
    """Запрос счёта: ключ только в заголовке, 404 — «ещё нет», 401 — ключ не подошёл, таймаут задан."""
    seen = {}

    def opener(req, timeout):
        seen.update(url=req.full_url, auth=req.get_header("Authorization"), timeout=timeout)
        if "missing" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b"{}"))
        if "denied" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b"{}"))
        return io.BytesIO(json.dumps({"data": {"id": GEN, "total_cost": 0.27}}).encode())
    monkeypatch.setattr(openrouter.urllib.request, "urlopen", opener)
    b = openrouter.Billing(autostart=False)
    assert b._fetch(GEN, FAKE_KEY) == pytest.approx(0.27)
    assert seen["url"].endswith("/api/v1/generation?id=" + GEN) and FAKE_KEY not in seen["url"]
    assert seen["auth"] == "Bearer " + FAKE_KEY and seen["timeout"] == openrouter.Billing.TIMEOUT
    with pytest.raises(openrouter.NotYet):
        b._fetch("gen-1-missing", FAKE_KEY)
    with pytest.raises(PermissionError) as e:
        b._fetch("gen-1-denied", FAKE_KEY)
    assert FAKE_KEY not in str(e.value)


def test_pause_question_marks_estimate():
    st = {"cost_limits": {"session": 1}}
    _, new = usage.watch(st, [{"w": "@1", "name": "glm", "sid": "s", "usd": 1.5, "src": "estimate"}], 0.0, TODAY)
    assert "потрачено по оценке $1.50" in usage.question(new[0])
    _, new = usage.watch(st, [{"w": "@1", "name": "c", "sid": "s", "usd": 1.5, "src": "anthropic"}], 0.0, TODAY)
    assert "потрачено $1.50" in usage.question(new[0])


# ---------- бюджет пространства ----------

def test_space_budget_uses_provider_price(tmp_path, monkeypatch):
    """Бюджет пространства на GLM: расход — оценка по тарифу Z.ai (а не 0 и не цена Claude Code), с пометкой;
    прошлые дни периода, уже записанные, не уменьшаются; пополнения работают как раньше."""
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    today = date.today()
    first = today - timedelta(days=1)
    cfg = sb.config({"daily_usd": 1, "period_days": 30, "start": first.isoformat()})
    proj = tmp_path / "claude" / "projects" / "-home-x"
    write(proj / "s.jsonl", answer("z1", "glm-5.3", ts=f"{today.isoformat()}T12:00:00Z", cost_usd=5.0,
                                   input_tokens=1_000_000, output_tokens=1_000_000))
    m = usage.Meter(billing=FakeBilling(tmp_path, {}))
    accs = m.days(tmp_path / "claude", first.isoformat(), detail=True)
    assert m.days(tmp_path / "claude", first.isoformat()) == {today.isoformat(): pytest.approx(5.8)}
    sb.save_store("demo", {"days": {first.isoformat(): 2.5}})                   # вчера уже записано
    spent = sb.remember("demo", {d: x["usd"] for d, x in accs.items()}, first)
    assert spent == {first.isoformat(): 2.5, today.isoformat(): pytest.approx(5.8)}
    sb.top_up("demo", 10, first)
    b = sb.state(cfg, spent, today, sb.extra("demo", first), source=usage.source(usage.merge(*accs.values())))
    assert b["spent"] == pytest.approx(8.3) and b["reserve"] == 40 and b["cost_source"] == "estimate"
    assert "оценка: токены × цены поставщика" in sb.text(b)
    b2 = sb.state(cfg, spent, today, source="provider")
    assert "по счёту OpenRouter" in sb.text(b2)
    assert "оценка" not in sb.text(sb.state(cfg, spent, today, source="anthropic"))
