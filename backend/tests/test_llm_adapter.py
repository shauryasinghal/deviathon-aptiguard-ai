"""LLM adapter contract tests against a FAKE `anthropic` module. No network, no API key, no installed SDK is needed:
the fake is placed in sys.modules for the duration of each test, so the real adapter code (client construction, prompt,
structured-output conversion, error mapping) is executed end to end."""
import sys
import types
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.generation import engine, llm_adapter
from app.services.generation.llm_adapter import LLMOption, LLMUnavailable, LLMVariant, LLMVariantBatch, generate_llm_variants

V1 = "/api/v1"
KEY = "test-not-real-key"

SOURCE = {"section": "QUANT", "skill": "percentages", "concept": "percentage change",
          "stem": "The price of a laptop rises from ₹400 to ₹500. What is the percentage increase?",
          "template_id": "SRC", "tags": ["pct"],
          "options": [{"key": "A", "text": "25%", "is_correct": True}, {"key": "B", "text": "20%", "is_correct": False},
                      {"key": "C", "text": "40%", "is_correct": False}, {"key": "D", "text": "30%", "is_correct": False}]}


def _settings(**kw) -> Settings:
    base = dict(_env_file=None, llm_provider="anthropic", llm_api_key=KEY, llm_model="test-model", llm_timeout_seconds=7)
    return Settings(**{**base, **kw})


class FakeSDK:
    """A stand-in for the `anthropic` package with the exception hierarchy the adapter relies on."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.behaviour = lambda kw: None
        m = types.ModuleType("anthropic")

        class APIError(Exception):
            pass

        class APIConnectionError(APIError):
            pass

        class APITimeoutError(APIConnectionError):
            pass

        class APIStatusError(APIError):
            def __init__(self, message, status_code):
                super().__init__(message)
                self.status_code = status_code

        class RateLimitError(APIStatusError):
            pass

        class APIResponseValidationError(APIError):
            pass

        sdk = self

        class Anthropic:
            def __init__(self, **kw):
                sdk.calls.append(("init", kw))
                self.messages = SimpleNamespace(parse=self._parse)

            @staticmethod
            def _parse(**kw):
                sdk.calls.append(("parse", kw))
                return sdk.behaviour(kw)

        for c in (APIError, APIConnectionError, APITimeoutError, APIStatusError, RateLimitError, APIResponseValidationError, Anthropic):
            setattr(m, c.__name__, c)
        self.module = m

    def __getattr__(self, name):  # exception classes by name, e.g. fake.APIStatusError
        return getattr(self.__dict__["module"], name)

    def parse_kwargs(self) -> dict:
        return next(kw for kind, kw in self.calls if kind == "parse")

    def init_kwargs(self) -> dict:
        return next(kw for kind, kw in self.calls if kind == "init")


@pytest.fixture()
def fake(monkeypatch):
    sdk = FakeSDK()
    monkeypatch.setitem(sys.modules, "anthropic", sdk.module)
    monkeypatch.setattr(llm_adapter, "get_settings", lambda: _settings())
    monkeypatch.setattr(engine, "get_settings", lambda: _settings())
    return sdk


def _variant(stem="A baker packs 18 rolls into 3 equal trays. How many rolls are in each tray?", correct="6",
             others=("5", "7", "9"), expr="18/3"):
    opts = [LLMOption(key=k, text=t, is_correct=(t == correct), rationale="why") for k, t in zip("ABCD", (correct, *others))]
    return LLMVariant(stem=stem, options=opts, explanation=f"{expr}", verification_expression=expr)


def _ok(*variants, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, parsed_output=LLMVariantBatch(variants=list(variants)))


# ------------------------------------------------------------------ success and conversion
def test_successful_structured_response_becomes_generated_items(fake):
    fake.behaviour = lambda kw: _ok(_variant(), _variant("A grocer splits 24 apples among 4 baskets equally. How many per basket?", "6", ("4", "8", "3"), "24/4"))
    items = generate_llm_variants(SOURCE, 2, "medium")
    assert len(items) == 2
    it = items[0]
    assert [o["key"] for o in it.options] == ["A", "B", "C", "D"] and sum(o["is_correct"] for o in it.options) == 1
    assert it.section == "QUANT" and it.skill == "percentages" and it.concept == "percentage change" and it.difficulty == "medium"
    assert it.params["llm_model"] == "test-model" and it.params["prompt_version"] == llm_adapter.PROMPT_VERSION
    assert it.params["verification_expression"] == "18/3"
    assert "reviewer must verify" in it.review_requirement  # the adapter itself marks LLM output as unproven
    assert it.tags == ["pct"] and it.template_id == "SRC"


def test_more_variants_than_requested_are_truncated(fake):
    fake.behaviour = lambda kw: _ok(*[_variant(stem=f"A baker packs {18 + i} rolls into 3 equal trays. How many in each tray?") for i in range(5)])
    assert len(generate_llm_variants(SOURCE, 2, "easy")) == 2


def test_sdk_is_called_with_configured_model_timeout_key_and_prompt(fake):
    fake.behaviour = lambda kw: _ok(_variant())
    generate_llm_variants(SOURCE, 3, "hard")
    init, call = fake.init_kwargs(), fake.parse_kwargs()
    assert init["api_key"] == KEY and init["timeout"] == 7.0
    assert call["model"] == "test-model" and call["output_format"] is LLMVariantBatch
    user = call["messages"][0]["content"]
    assert SOURCE["stem"] in user and "Target difficulty: hard" in user and "Write 3 parallel variants" in user
    assert "(correct)" in user and "verification_expression" in user  # quantitative items ask for a checkable expression
    assert "Never copy the source wording" in call["system"]


def test_verbal_prompt_does_not_ask_for_a_verification_expression(fake):
    fake.behaviour = lambda kw: _ok(_variant())
    generate_llm_variants({**SOURCE, "section": "VERBAL"}, 1, "easy")
    assert "verification_expression" not in fake.parse_kwargs()["messages"][0]["content"]


# ------------------------------------------------------------------ empty / refused / provider failures
@pytest.mark.parametrize("response", [
    SimpleNamespace(stop_reason="end_turn", parsed_output=None),
    SimpleNamespace(stop_reason="max_tokens", parsed_output=None),
    SimpleNamespace(stop_reason="refusal", parsed_output=LLMVariantBatch(variants=[_variant()])),  # refusal wins over content
])
def test_empty_truncated_or_refused_output_is_an_explicit_failure(fake, response):
    fake.behaviour = lambda kw: response
    with pytest.raises(LLMUnavailable) as e:
        generate_llm_variants(SOURCE, 1, "medium")
    assert "no usable output" in str(e.value) and response.stop_reason in str(e.value)


def test_batch_with_no_variants_returns_nothing_to_validate(fake):
    fake.behaviour = lambda kw: _ok()
    assert generate_llm_variants(SOURCE, 2, "medium") == []


def test_connection_and_timeout_errors_are_mapped(fake):
    for exc in (fake.APIConnectionError("boom " + KEY), fake.APITimeoutError("slow")):
        fake.behaviour = lambda kw, exc=exc: (_ for _ in ()).throw(exc)
        with pytest.raises(LLMUnavailable) as e:
            generate_llm_variants(SOURCE, 1, "medium")
        assert "unreachable" in str(e.value)
        assert KEY not in str(e.value)  # provider text is not echoed: it could contain credentials or prompts


@pytest.mark.parametrize("status", [401, 429, 500, 529])
def test_http_status_errors_are_mapped_with_only_the_status_code(fake, status):
    err = (fake.RateLimitError if status == 429 else fake.APIStatusError)("provider said: " + KEY, status)
    fake.behaviour = lambda kw: (_ for _ in ()).throw(err)
    with pytest.raises(LLMUnavailable) as e:
        generate_llm_variants(SOURCE, 1, "medium")
    assert str(e.value) == f"LLM provider error HTTP {status}"


def test_malformed_structured_output_is_an_llm_failure_not_a_crash(fake):
    def bad(kw):
        LLMVariantBatch.model_validate({"variants": [{"stem": "x"}]})  # missing options/explanation -> pydantic error

    fake.behaviour = bad
    with pytest.raises(ValidationError):  # confirms the fake really produces the SDK-style failure
        bad({})
    with pytest.raises(LLMUnavailable) as e:
        generate_llm_variants(SOURCE, 1, "medium")
    assert "malformed" in str(e.value)


@pytest.mark.parametrize("make", [lambda f: f.APIResponseValidationError("schema"), lambda f: ValueError("not json"),
                                  lambda f: f.APIError("other sdk failure")])
def test_other_sdk_and_parsing_failures_are_mapped(fake, make):
    err = make(fake)
    fake.behaviour = lambda kw: (_ for _ in ()).throw(err)
    with pytest.raises(LLMUnavailable):
        generate_llm_variants(SOURCE, 1, "medium")


# ------------------------------------------------------------------ configuration
@pytest.mark.parametrize("kw", [dict(llm_provider="none"), dict(llm_api_key=""), dict(llm_provider="openai")])
def test_missing_or_unsupported_configuration_is_reported_without_calling_the_sdk(fake, monkeypatch, kw):
    monkeypatch.setattr(llm_adapter, "get_settings", lambda: _settings(**kw))
    with pytest.raises(LLMUnavailable) as e:
        generate_llm_variants(SOURCE, 1, "medium")
    assert "not configured" in str(e.value) and fake.calls == []


def test_missing_sdk_package_is_reported_with_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)  # makes `import anthropic` raise ImportError
    monkeypatch.setattr(llm_adapter, "get_settings", lambda: _settings())
    with pytest.raises(LLMUnavailable) as e:
        generate_llm_variants(SOURCE, 1, "medium")
    assert "requirements-llm.txt" in str(e.value)


# ------------------------------------------------------------------ through the real route (fake SDK, throw-away DB)
def _source(client, auth):
    return client.get(f"{V1}/questions?q=QNT-PCT-M3-S", headers=auth("designer")).json()["items"][0]


def _queue_total(client, auth):
    return client.get(f"{V1}/review/queue", headers=auth("reviewer")).json()["total"]


def test_route_stores_valid_llm_items_as_pending_and_invalid_ones_as_rejected_never_approved(client, auth, fake):
    good = _variant("A florist ties 40 roses into 8 equal bunches. How many roses are in each bunch?", "5", ("4", "6", "8"), "40/8")
    wrong_key = _variant("A florist arranges 24 tulips equally in 4 vases. How many tulips are in each vase?", "5", ("4", "7", "8"), "24/4")
    fake.behaviour = lambda kw: _ok(good, wrong_key)
    src = _source(client, auth)
    r = client.post(f"{V1}/questions/{src['id']}/variants:generate", json={"n": 2, "method": "llm"}, headers=auth("designer"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["run"]["method"] == "llm" and body["run"]["provider"] == "anthropic" and body["run"]["model"] == "test-model"
    assert [c["status"] for c in body["created"]] == ["pending_review"]  # nothing is approved by generation
    assert body["created"][0]["generation_method"] == "llm"
    assert len(body["rejections"]) == 1 and any("key is" in x or "Expression" in x for x in body["rejections"][0]["reasons"])
    # the pending item cannot be approved by its author, and the auto-rejected one cannot be approved at all
    pending_id = body["created"][0]["id"]
    assert client.post(f"{V1}/review/{pending_id}/decision", json={"decision": "approve"}, headers=auth("designer")).status_code == 403
    rejected = [q for q in client.get(f"{V1}/questions?q={body['created'][0]['code'].rsplit('-', 1)[0]}", headers=auth("designer")).json()["items"]
                if q["status"] == "rejected" and q["generation_method"] == "llm"]
    assert rejected, "the invalid LLM candidate is kept for audit as 'rejected'"
    r2 = client.post(f"{V1}/review/{rejected[0]['id']}/decision", json={"decision": "approve"}, headers=auth("reviewer"))
    assert r2.status_code == 409 and "pending review" in r2.json()["error"]["message"]


@pytest.mark.parametrize("exc_name,args,expect", [("APIConnectionError", ("down",), "unreachable"),
                                                   ("APIStatusError", ("nope", 503), "HTTP 503")])
def test_route_reports_provider_failures_as_422_and_creates_nothing(client, auth, fake, exc_name, args, expect):
    fake.behaviour = lambda kw: (_ for _ in ()).throw(getattr(fake, exc_name)(*args))
    src = _source(client, auth)
    before = _queue_total(client, auth)
    r = client.post(f"{V1}/questions/{src['id']}/variants:generate", json={"n": 2, "method": "llm"}, headers=auth("designer"))
    assert r.status_code == 422 and expect in r.json()["error"]["message"] and KEY not in r.text
    assert _queue_total(client, auth) == before
    last = client.get(f"{V1}/generation-runs?source_id={src['id']}&limit=1", headers=auth("designer")).json()[0]
    assert last["status"] == "failed" and last["method"] == "llm" and expect in last["message"]


def test_route_reports_malformed_output_as_422_not_500(client, auth, fake):
    def bad(kw):
        LLMVariantBatch.model_validate({"variants": "not a list"})

    fake.behaviour = bad
    src = _source(client, auth)
    r = client.post(f"{V1}/questions/{src['id']}/variants:generate", json={"n": 1, "method": "llm"}, headers=auth("designer"))
    assert r.status_code == 422 and "malformed" in r.json()["error"]["message"]


def test_route_with_an_empty_batch_records_a_failed_run_and_creates_nothing(client, auth, fake):
    fake.behaviour = lambda kw: _ok()
    src = _source(client, auth)
    before = _queue_total(client, auth)
    r = client.post(f"{V1}/questions/{src['id']}/variants:generate", json={"n": 2, "method": "llm"}, headers=auth("designer"))
    assert r.status_code == 201 and r.json()["created"] == [] and r.json()["run"]["status"] == "failed"
    assert _queue_total(client, auth) == before
