import pytest
from unittest.mock import patch
from medicine_sync import sync_medicine_reminders

def test_sync_medicine_reminders_duplicate_times():
    medicines = [
        {"name": "Med A", "reminder_time": "08:00"},
        {"name": "Med B", "reminder_time": "08:00"},
        {"name": "Med C", "reminder_time": "20:00"}
    ]
    with patch("medicine_sync.plan_limits", return_value={"reminders": 5}):
        result = sync_medicine_reminders(medicines, [], "nitya")
        assert len(result["synced_times"]) == 2
        assert "08:00" in result["synced_times"]
        assert "20:00" in result["synced_times"]
        assert len(result["dropped"]) == 0

def test_sync_medicine_reminders_over_limit():
    medicines = [
        {"name": "Med A", "reminder_time": f"0{i}:00"} for i in range(1, 6)
    ]
    with patch("medicine_sync.plan_limits", return_value={"reminders": 3}):
        result = sync_medicine_reminders(medicines, [], "nitya")
        assert len(result["synced_times"]) == 3
        assert len(result["dropped"]) == 2

def test_sync_medicine_reminders_manual_reminders_reduce_slots():
    medicines = [
        {"name": "Med A", "reminder_time": "08:00"},
        {"name": "Med B", "reminder_time": "20:00"}
    ]
    existing = [
        {"category": "water", "time": "10:00", "source": None} # Manual reminder
    ]
    with patch("medicine_sync.plan_limits", return_value={"reminders": 2}):
        # Limit 2, 1 used by manual water, 1 left for medicines
        result = sync_medicine_reminders(medicines, existing, "nitya")
        assert len(result["synced_times"]) == 1
        assert len(result["dropped"]) == 1
        assert result["messages"][0] == existing[0]

def test_sync_medicine_reminders_zero_medicines():
    existing = [
        {"category": "morning_wish", "time": "08:00", "source": None}
    ]
    with patch("medicine_sync.plan_limits", return_value={"reminders": 5}):
        result = sync_medicine_reminders([], existing, "nitya")
        assert len(result["synced_times"]) == 0
        assert len(result["dropped"]) == 0
        assert result["messages"] == existing # Unchanged manual messages
