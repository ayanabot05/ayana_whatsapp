import pytest

from pricing import (
    resolve_plan_id,
    plan_limits,
    get_template_cost_estimate,
    PLAN_BY_ID,
    CURRENCIES
)

def test_resolve_plan_id():
    assert resolve_plan_id("basic") == "nitya"
    assert resolve_plan_id("care_plus") == "bandham"
    assert resolve_plan_id("raksha") == "raksha"
    assert resolve_plan_id("unknown") == "unknown"

def test_plan_limits():
    nitya = plan_limits("nitya")
    assert nitya["parents"] == 1
    assert nitya["checkins"] == 2

    bandham = plan_limits("bandham")
    assert bandham["parents"] == 2
    assert bandham["checkins"] == 3

    raksha = plan_limits("raksha")
    assert raksha["recovery_mode"] is True
    assert raksha["parents"] == 2

def test_get_template_cost_estimate():
    # nitya: 2 checkins + 2 reminders = 4 total
    c1 = get_template_cost_estimate("nitya")
    assert c1["total_scheduled"] == 4
    assert c1["paid_best_case"] == 1
    assert c1["paid_worst_case"] == 4
    assert c1["free_quick_replies_best_case"] == 3

    # bandham: 3 checkins + 3 reminders = 6 total
    c2 = get_template_cost_estimate("bandham")
    assert c2["total_scheduled"] == 6

    # raksha: 4 checkins + 4 reminders = 8 total
    c3 = get_template_cost_estimate("raksha")
    assert c3["total_scheduled"] == 8

def test_invalid_plan_id_keyerror():
    # PLAN_BY_ID is a dict, accessing a missing key directly should raise KeyError
    with pytest.raises(KeyError):
        _ = PLAN_BY_ID["invalid_plan_xyz"]
    
    # As an extra, ensure plan_limits returns nitya fallback if passed an invalid plan
    assert plan_limits("invalid_plan_xyz") == plan_limits("nitya")

def test_currency_matrix():
    assert len(CURRENCIES) == 7
    codes = [c["code"] for c in CURRENCIES]
    for code in ["USD", "GBP", "EUR", "AED", "SGD", "AUD", "CAD"]:
        assert code in codes
