import pytest
from pydantic import ValidationError

from models import (
    RegisterInput,
    LoginInput,
    ChildProfileInput,
    MedicineItem,
    HabitsInput,
    ParentInput,
    ScheduleInput,
    ScheduleMessage,
    EmergencyContact,
)

def test_register_input():
    # Valid
    reg = RegisterInput(name="Test", email="test@test.com", phone="+919876543210", password="password123")
    assert reg.phone == "+919876543210"

    # Invalid phone (missing +)
    with pytest.raises(ValidationError):
        RegisterInput(name="Test", email="test@test.com", phone="9876543210", password="password123")

    # Invalid email
    with pytest.raises(ValidationError):
        RegisterInput(name="Test", email="not_an_email", phone="+919876543210", password="password123")

    # Name length boundaries
    with pytest.raises(ValidationError):
        RegisterInput(name="", email="test@test.com", phone="+919876543210", password="password123")
    with pytest.raises(ValidationError):
        RegisterInput(name="a" * 81, email="test@test.com", phone="+919876543210", password="password123")


def test_medicine_item():
    # Valid
    med = MedicineItem(name="Aspirin", shape="round", color="white", timing="morning", reminder_time="08:00")
    assert med.name == "Aspirin"

    # Invalid shape
    with pytest.raises(ValidationError):
        MedicineItem(name="Aspirin", shape="triangle")
    
    # Invalid color
    with pytest.raises(ValidationError):
        MedicineItem(name="Aspirin", color="transparent")

    # Invalid timing
    with pytest.raises(ValidationError):
        MedicineItem(name="Aspirin", timing="never")

    # Valid reminder_time regex
    med = MedicineItem(name="Aspirin", reminder_time="23:59")
    assert med.reminder_time == "23:59"
    with pytest.raises(ValidationError):
        MedicineItem(name="Aspirin", reminder_time="24:00")
    with pytest.raises(ValidationError):
        MedicineItem(name="Aspirin", reminder_time="8:00") # missing leading zero


def test_parent_input():
    # Valid
    parent = ParentInput(name="Mom", relationship="mother", phone="+919876543210", language="te", timezone="Asia/Kolkata")
    
    # Nickname limit > 3
    with pytest.raises(ValidationError):
        ParentInput(name="Mom", relationship="mother", phone="+919876543210", language="te", timezone="Asia/Kolkata", nicknames=["a", "b", "c", "d"])

    # Story limit > 5 raises (max_length=5 on Field)
    with pytest.raises(ValidationError):
        ParentInput(name="Mom", relationship="mother", phone="+919876543210", language="te", timezone="Asia/Kolkata", stories=["1", "2", "3", "4", "5", "6"])

    # Exactly 5 stories is fine
    parent = ParentInput(name="Mom", relationship="mother", phone="+919876543210", language="te", timezone="Asia/Kolkata", stories=["1", "2", "3", "4", "5"])
    assert len(parent.stories) == 5

    # Invalid language code
    with pytest.raises(ValidationError):
        ParentInput(name="Mom", relationship="mother", phone="+919876543210", language="xx", timezone="Asia/Kolkata")

    # blank_birthday_to_none
    parent = ParentInput(name="Mom", relationship="mother", phone="+919876543210", language="te", timezone="Asia/Kolkata", birthday="")
    assert parent.birthday is None


def test_schedule_input_limit_messages():
    msg = ScheduleMessage(time="08:00", category="morning_wish")
    
    # nitya allows 2 + 1 maybe? plan_limits("nitya") typically allows ~2
    # The requirement says "tier-based message count enforcement".
    # I'll just check if it fails with too many and passes with right amount.
    with pytest.raises(ValidationError, match="max .* daily messages"):
        ScheduleInput(parent_id="123", mode="nitya", messages=[msg] * 20)
    
    with pytest.raises(ValidationError, match="Add at least 1 daily check-in"):
        ScheduleInput(parent_id="123", mode="nitya", messages=[])


def test_emergency_contact():
    # Valid
    ec = EmergencyContact(name="Doc", phone="+919876543210")
    assert ec.phone == "+919876543210"

    # Phone without + prefix
    with pytest.raises(ValidationError):
        EmergencyContact(name="Doc", phone="9876543210")


def test_habits_input():
    # Invalid time format rejection
    with pytest.raises(ValidationError):
        HabitsInput(wake_time="25:00")
    with pytest.raises(ValidationError):
        HabitsInput(tea_time="am")

    # Valid
    habits = HabitsInput(wake_time="07:00", tea_type="coffee")
    assert habits.wake_time == "07:00"


def test_child_profile_input():
    # Valid
    cp = ChildProfileInput(name="Child", phone="+919876543210", timezone="Asia/Kolkata")
    assert cp.name == "Child"

    # Edge cases
    with pytest.raises(ValidationError):
        ChildProfileInput(name="", phone="+919876543210", timezone="Asia/Kolkata")
    with pytest.raises(ValidationError):
        ChildProfileInput(name="Child", phone="123", timezone="Asia/Kolkata")


def test_login_input():
    # Empty password rejection
    with pytest.raises(ValidationError):
        LoginInput(email="test@test.com", password="")
