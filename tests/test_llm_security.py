from __future__ import annotations

import pytest

from litwatch.config import Settings
from litwatch.llm.security import (
    CostGuard,
    DataEgressPolicy,
    LLMSecurityError,
    LLMSecurityErrorCode,
)


def test_cloud_provider_requires_explicit_egress_consent():
    policy = DataEgressPolicy(
        cloud_egress_consent=False,
        fulltext_egress_consent=False,
        max_payload_chars=10_000,
    )

    with pytest.raises(LLMSecurityError) as error:
        policy.authorize("cloud", "abstract", 500)

    assert error.value.code is LLMSecurityErrorCode.CLOUD_CONSENT_REQUIRED
    assert str(error.value) == "Cloud LLM data egress is not authorized"


@pytest.mark.parametrize("evidence_scope", ["fulltext_excerpt", "fulltext"])
def test_cloud_fulltext_requires_separate_opt_in(evidence_scope):
    policy = DataEgressPolicy(
        cloud_egress_consent=True,
        fulltext_egress_consent=False,
        max_payload_chars=10_000,
    )

    with pytest.raises(LLMSecurityError) as error:
        policy.authorize("cloud", evidence_scope, 500)

    assert error.value.code is LLMSecurityErrorCode.FULLTEXT_CONSENT_REQUIRED


def test_cloud_abstract_is_allowed_after_general_consent():
    policy = DataEgressPolicy(
        cloud_egress_consent=True,
        fulltext_egress_consent=False,
        max_payload_chars=10_000,
    )

    policy.authorize("cloud", "abstract", 500)


def test_payload_limit_is_enforced_for_local_and_cloud_providers():
    for provider_kind in ("local", "cloud"):
        policy = DataEgressPolicy(
            cloud_egress_consent=True,
            fulltext_egress_consent=True,
            max_payload_chars=100,
        )
        with pytest.raises(LLMSecurityError) as error:
            policy.authorize(provider_kind, "abstract", 101)
        assert error.value.code is LLMSecurityErrorCode.PAYLOAD_LIMIT_EXCEEDED


def test_local_provider_does_not_require_cloud_or_fulltext_consent():
    policy = DataEgressPolicy(
        cloud_egress_consent=False,
        fulltext_egress_consent=False,
        max_payload_chars=1_000,
    )

    policy.authorize("local", "fulltext", 999)


@pytest.mark.parametrize("provider_kind", ["", "remote", "CLOUD"])
def test_unknown_provider_kind_is_rejected(provider_kind):
    policy = DataEgressPolicy(
        cloud_egress_consent=True,
        fulltext_egress_consent=True,
        max_payload_chars=1_000,
    )

    with pytest.raises(ValueError, match="provider_kind"):
        policy.authorize(provider_kind, "abstract", 10)


def _guard() -> CostGuard:
    return CostGuard(
        max_tokens_per_job=1_000,
        max_cost_per_job=0.50,
        max_daily_cost=2.00,
        max_concurrent_llm_jobs=2,
    )


def test_cost_guard_allows_request_within_all_limits():
    _guard().authorize(
        estimated_tokens=1_000,
        estimated_cost=0.50,
        daily_spend=1.50,
        active_jobs=1,
    )


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"estimated_tokens": 1_001}, LLMSecurityErrorCode.TOKEN_LIMIT_EXCEEDED),
        ({"estimated_cost": 0.51}, LLMSecurityErrorCode.JOB_COST_LIMIT_EXCEEDED),
        ({"daily_spend": 1.51}, LLMSecurityErrorCode.DAILY_COST_LIMIT_EXCEEDED),
        ({"active_jobs": 2}, LLMSecurityErrorCode.CONCURRENCY_LIMIT_EXCEEDED),
    ],
)
def test_cost_guard_rejects_each_limit_before_dispatch(overrides, expected_code):
    values = {
        "estimated_tokens": 1_000,
        "estimated_cost": 0.50,
        "daily_spend": 1.50,
        "active_jobs": 1,
    }
    values.update(overrides)

    with pytest.raises(LLMSecurityError) as error:
        _guard().authorize(**values)

    assert error.value.code is expected_code
    assert "secret" not in str(error.value).lower()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("estimated_tokens", -1),
        ("estimated_cost", -0.01),
        ("daily_spend", -0.01),
        ("active_jobs", -1),
    ],
)
def test_cost_guard_rejects_negative_runtime_measurements(field, value):
    values = {
        "estimated_tokens": 100,
        "estimated_cost": 0.10,
        "daily_spend": 0.20,
        "active_jobs": 0,
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        _guard().authorize(**values)


@pytest.mark.parametrize("value", [True, 1.5, float("nan"), float("inf")])
def test_payload_chars_rejects_non_integral_or_non_finite_values(value):
    policy = DataEgressPolicy(
        cloud_egress_consent=True,
        fulltext_egress_consent=True,
        max_payload_chars=1_000,
    )

    with pytest.raises((TypeError, ValueError), match="payload_chars"):
        policy.authorize("cloud", "abstract", value)


@pytest.mark.parametrize("field", ["estimated_tokens", "active_jobs"])
@pytest.mark.parametrize("value", [True, 1.5, float("nan"), float("inf")])
def test_integer_runtime_measurements_reject_bool_fraction_and_non_finite(
    field, value
):
    values = {
        "estimated_tokens": 100,
        "estimated_cost": 0.10,
        "daily_spend": 0.20,
        "active_jobs": 0,
    }
    values[field] = value

    with pytest.raises((TypeError, ValueError), match=field):
        _guard().authorize(**values)


@pytest.mark.parametrize("field", ["estimated_cost", "daily_spend"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_cost_runtime_measurements_reject_non_finite_values(field, value):
    values = {
        "estimated_tokens": 100,
        "estimated_cost": 0.10,
        "daily_spend": 0.20,
        "active_jobs": 0,
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        _guard().authorize(**values)


def test_settings_expose_fail_closed_llm_security_defaults():
    settings = Settings(_env_file=None)

    assert settings.llm_cloud_egress_consent is False
    assert settings.llm_fulltext_egress_consent is False
    assert settings.llm_max_payload_chars > 0
    assert settings.max_tokens_per_job > 0
    assert settings.max_cost_per_job > 0
    assert settings.max_daily_cost >= settings.max_cost_per_job
    assert settings.max_concurrent_llm_jobs > 0


def test_settings_load_exact_llm_security_environment_names(monkeypatch):
    monkeypatch.setenv("LITWATCH_LLM_CLOUD_EGRESS_CONSENT", "true")
    monkeypatch.setenv("LITWATCH_LLM_FULLTEXT_EGRESS_CONSENT", "true")
    monkeypatch.setenv("LITWATCH_LLM_MAX_PAYLOAD_CHARS", "12345")
    monkeypatch.setenv("LITWATCH_MAX_TOKENS_PER_JOB", "2345")
    monkeypatch.setenv("LITWATCH_MAX_COST_PER_JOB", "1.25")
    monkeypatch.setenv("LITWATCH_MAX_DAILY_COST", "4.5")
    monkeypatch.setenv("LITWATCH_MAX_CONCURRENT_LLM_JOBS", "3")

    settings = Settings(_env_file=None)

    assert settings.llm_cloud_egress_consent is True
    assert settings.llm_fulltext_egress_consent is True
    assert settings.llm_max_payload_chars == 12_345
    assert settings.max_tokens_per_job == 2_345
    assert settings.max_cost_per_job == 1.25
    assert settings.max_daily_cost == 4.5
    assert settings.max_concurrent_llm_jobs == 3
