import pytest
from unittest.mock import AsyncMock

from interactive_button_handler import (
    is_interactive_button_reply,
    extract_button_payload,
    handle_interactive_reply
)

def test_is_interactive_button_reply():
    valid = {
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "button_reply": {"id": "medicine_done"}
        }
    }
    assert is_interactive_button_reply(valid) is True
    
    invalid = {"type": "text", "text": {"body": "hello"}}
    assert is_interactive_button_reply(invalid) is False

def test_extract_button_payload():
    msg = {
        "interactive": {
            "button_reply": {"id": "meal_yes"}
        }
    }
    assert extract_button_payload(msg) == "meal_yes"
    assert extract_button_payload({}) is None

@pytest.mark.asyncio
async def test_handle_interactive_reply():
    mock_med = AsyncMock()
    mock_meal = AsyncMock()
    mock_send = AsyncMock()
    phone = "+123"

    # Non-interactive message -> returns False
    msg_text = {"type": "text"}
    handled = await handle_interactive_reply(
        msg_text, from_number=phone,
        mark_medicine_status=mock_med, mark_meal_status=mock_meal, send_whatsapp_text=mock_send
    )
    assert handled is False

    # medicine_done
    msg_done = {
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": "medicine_done"}}
    }
    handled = await handle_interactive_reply(
        msg_done, from_number=phone,
        mark_medicine_status=mock_med, mark_meal_status=mock_meal, send_whatsapp_text=mock_send
    )
    assert handled is True
    mock_med.assert_called_with(phone, taken=True)

    # meal_not_yet
    mock_med.reset_mock()
    msg_meal = {
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": "meal_not_yet"}}
    }
    handled = await handle_interactive_reply(
        msg_meal, from_number=phone,
        mark_medicine_status=mock_med, mark_meal_status=mock_meal, send_whatsapp_text=mock_send
    )
    assert handled is True
    mock_meal.assert_called_with(phone, eaten=False)

    # Unknown button ID -> fallback error message
    mock_send.reset_mock()
    msg_unknown = {
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": "unknown_btn"}}
    }
    handled = await handle_interactive_reply(
        msg_unknown, from_number=phone,
        mark_medicine_status=mock_med, mark_meal_status=mock_meal, send_whatsapp_text=mock_send
    )
    assert handled is True
    assert mock_send.call_count == 1
    assert "didn't recognize" in mock_send.call_args[0][1]
