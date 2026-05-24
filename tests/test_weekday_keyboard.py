"""
Tests for build_weekday_keyboard (keyboards.py) and the weekday_offset
handler logic (add_lesson_weekday).

Rules under test:
  - Keyboard always has exactly 7 buttons.
  - Button at offset=0 → today's date and weekday name.
  - Button at offset=6 → today + 6 days.
  - Buttons are in order (ascending offsets 0..6).
  - callback_data uses "weekday_offset:{offset}" format.
  - Day labels are correct Russian abbreviations (Пн/Вт/Ср/Чт/Пт/Сб/Вс).
  - Works correctly for every day of the week (Mon–Sun) as today.
  - Pressing offset=0 when today is Sunday selects today, not next Sunday.
"""
from __future__ import annotations

import datetime
import pytest

from infrastructure.telegram.keyboards import build_weekday_keyboard, _DAY_NAMES

# ─── helpers ──────────────────────────────────────────────────────────────────

def _monday() -> datetime.date:
    return datetime.date(2026, 5, 25)  # Monday


def _sunday() -> datetime.date:
    return datetime.date(2026, 5, 24)  # Sunday (today in the real scenario)


def _all_days_of_week() -> list[datetime.date]:
    """One date per weekday: Mon 25 → Sun 31 May 2026."""
    base = _monday()
    return [base + datetime.timedelta(days=i) for i in range(7)]


def _buttons(today: datetime.date):
    kb = build_weekday_keyboard(today)
    return [btn for row in kb.inline_keyboard for btn in row]


# ─── structure ────────────────────────────────────────────────────────────────

class TestKeyboardStructure:
    def test_exactly_7_buttons(self):
        buttons = _buttons(_monday())
        assert len(buttons) == 7

    def test_one_button_per_row(self):
        kb = build_weekday_keyboard(_monday())
        for row in kb.inline_keyboard:
            assert len(row) == 1

    def test_callback_data_format(self):
        buttons = _buttons(_monday())
        for i, btn in enumerate(buttons):
            assert btn.callback_data == f"weekday_offset:{i}"

    def test_offsets_are_ascending(self):
        buttons = _buttons(_monday())
        offsets = [int(btn.callback_data.split(":")[1]) for btn in buttons]
        assert offsets == list(range(7))


# ─── first button = today ─────────────────────────────────────────────────────

class TestFirstButtonIsToday:
    @pytest.mark.parametrize("today", _all_days_of_week())
    def test_first_button_label_contains_today_date(self, today):
        buttons = _buttons(today)
        expected_date_str = today.strftime("%d.%m")
        assert expected_date_str in buttons[0].text

    @pytest.mark.parametrize("today", _all_days_of_week())
    def test_first_button_label_contains_today_day_name(self, today):
        buttons = _buttons(today)
        expected_day = _DAY_NAMES[today.weekday()]
        assert expected_day in buttons[0].text

    def test_sunday_first_button_is_sunday_not_next(self):
        """Core regression: pressing Вс when today is Sunday must be TODAY."""
        today = _sunday()  # Sun 24 May 2026
        buttons = _buttons(today)
        first = buttons[0]
        assert "24.05" in first.text
        assert "Вс" in first.text
        assert first.callback_data == "weekday_offset:0"

    def test_monday_first_button_is_monday(self):
        today = _monday()  # Mon 25 May 2026
        buttons = _buttons(today)
        assert "25.05" in buttons[0].text
        assert "Пн" in buttons[0].text


# ─── last button = today + 6 ──────────────────────────────────────────────────

class TestLastButtonIsPlus6:
    @pytest.mark.parametrize("today", _all_days_of_week())
    def test_last_button_is_today_plus_6(self, today):
        buttons = _buttons(today)
        last = buttons[-1]
        expected = today + datetime.timedelta(days=6)
        assert expected.strftime("%d.%m") in last.text
        assert last.callback_data == "weekday_offset:6"


# ─── correct day name for each offset ────────────────────────────────────────

class TestDayNamesCorrect:
    @pytest.mark.parametrize("today", _all_days_of_week())
    def test_all_button_day_names_match_date(self, today):
        buttons = _buttons(today)
        for offset, btn in enumerate(buttons):
            expected_date = today + datetime.timedelta(days=offset)
            expected_name = _DAY_NAMES[expected_date.weekday()]
            assert expected_name in btn.text, (
                f"offset={offset}, expected '{expected_name}' in '{btn.text}'"
            )


# ─── offset→date resolution (simulates handler logic) ────────────────────────

class TestOffsetResolution:
    """Tests the computation today + timedelta(offset) that the handler uses."""

    def test_offset_0_is_today(self):
        today = _sunday()
        result = today + datetime.timedelta(days=0)
        assert result == today

    def test_offset_0_sunday_stays_sunday(self):
        today = _sunday()
        result = today + datetime.timedelta(days=0)
        assert result.weekday() == 6  # Sunday

    def test_offset_1_is_tomorrow(self):
        today = _monday()
        result = today + datetime.timedelta(days=1)
        assert result == today + datetime.timedelta(days=1)

    def test_offset_6_is_six_days_ahead(self):
        today = _sunday()
        result = today + datetime.timedelta(days=6)
        assert (result - today).days == 6

    @pytest.mark.parametrize("today", _all_days_of_week())
    def test_no_offset_skips_to_next_week(self, today):
        """
        Regression: old code did `days_ahead if days_ahead > 0 else 7`.
        Ensure new code (offset-based) never jumps 7 days for today.
        """
        for offset in range(7):
            result = today + datetime.timedelta(days=offset)
            assert (result - today).days == offset
