import pytest
from templates_data import (
    get_nicknames_for_day,
    seasonal_greeting,
    trim_variants_for_plan,
    render_slot_body,
    render_slot_buttons,
    category_type
)

def test_get_nicknames_for_day():
    parent_3 = {"nicknames": ["Nick1", "Nick2", "Nick3"]}
    assert get_nicknames_for_day(parent_3, 0) == ("Nick1", "Nick2", "Nick3")
    assert get_nicknames_for_day(parent_3, 1) == ("Nick2", "Nick3", "Nick1")
    
    parent_1 = {"nicknames": ["OnlyNick"]}
    assert get_nicknames_for_day(parent_1, 0) == ("OnlyNick", "OnlyNick", "OnlyNick")
    
    parent_0 = {"name": "Bob"}
    assert get_nicknames_for_day(parent_0, 0) == ("Bob", "Bob", "Bob")

def test_seasonal_greeting():
    assert seasonal_greeting("en", month=1) == "a bit cold" # winter
    assert seasonal_greeting("en", month=5) == "quite warm" # summer
    assert seasonal_greeting("en", month=7) == "rainy"      # monsoon
    assert seasonal_greeting("en", month=10) == "pleasant"  # pleasant

    assert seasonal_greeting("te", month=1) == "చలిగా ఉందా"
    assert seasonal_greeting("hi", month=5) == "गर्मी है"

def test_trim_variants_for_plan():
    variants = ["1", "2", "3", "4", "5"]
    assert trim_variants_for_plan(variants, 3) == ["1", "2", "3"]
    assert trim_variants_for_plan(variants, 10) == variants

def test_render_slot_body():
    parent = {
        "name": "Mom",
        "nicknames": ["Amma"],
        "city": "Hyderabad",
        "habits": {"tea_type": "coffee"}
    }
    
    # Morning wish (en)
    body = render_slot_body("morning_wish", "en", parent, day_index=0)
    assert "Amma" in body
    assert "Hyderabad" in body
    
    # Tea check (te) - should translate coffee correctly
    body = render_slot_body("tea_check", "te", parent, day_index=0)
    assert "కాఫీ" in body # Translated tea_type
    
def test_render_slot_buttons():
    btns = render_slot_buttons("morning_wish", "en")
    assert len(btns) <= 3
    assert btns[0][0] == "Good 😊"
    assert btns[0][1] == "feeling:good"
    
    for label, payload in btns:
        assert len(label) <= 20 # Title limit

def test_category_type():
    assert category_type("medicine") == "reminder"
    assert category_type("sugar_check") == "reminder"
    assert category_type("morning_wish") == "checkin"
    assert category_type("lunch") == "checkin"
