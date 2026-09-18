import pytest
from app.interpreter import (
    parse_time_window,
    fallback_nlp_interpreter,
    validate_and_sanitize_directive
)
from app.models import (
    BatteryConfig,
    DirectiveType
)

@pytest.fixture
def sample_battery():
    return BatteryConfig(
        capacity_kwh=200,
        initial_energy_kwh=100,
        minimum_energy_kwh=40,
        max_charge_kwh_per_hour=50,
        max_discharge_kwh_per_hour=50
    )

def test_parse_time_window():
    assert parse_time_window("from 1 PM to 3 PM") == [13, 14]
    assert parse_time_window("from noon until 2 PM") == [12, 13]
    assert parse_time_window("from 2 AM until 5 AM") == [2, 3, 4]
    assert parse_time_window("from 6 PM until 9 PM") == [18, 19, 20]
    assert parse_time_window("from 6 PM until 8 PM") == [18, 19]

def test_solar_reduction_interpretation(sample_battery):
    note = "Facilities will wash the rooftop solar panels from noon until 2 PM. Usable solar roughly 25% of forecast."
    interp = fallback_nlp_interpreter(note, 0, sample_battery)
    
    assert interp.note_index == 0
    assert interp.applies is True
    assert interp.directive_type == DirectiveType.SOLAR_REDUCTION
    assert interp.structured_adjustment.hours == [12, 13]
    assert interp.structured_adjustment.factor == 0.25

def test_no_charge_interpretation(sample_battery):
    note = "The battery charger will be isolated from 2 AM until 5 AM for electrical maintenance."
    interp = fallback_nlp_interpreter(note, 0, sample_battery)

    assert interp.applies is True
    assert interp.directive_type == DirectiveType.NO_CHARGE_WINDOW
    assert interp.structured_adjustment.hours == [2, 3, 4]

def test_no_op_distractor(sample_battery):
    note = "The sports office moved next month's registration deadline."
    interp = fallback_nlp_interpreter(note, 1, sample_battery)

    assert interp.note_index == 1
    assert interp.applies is False
    assert interp.directive_type == DirectiveType.NO_OP
    assert interp.structured_adjustment is None

def test_guardrails_sanitize_hours(sample_battery):
    raw_d = {
        "directive_type": "no_charge_window",
        "structured_adjustment": {"hours": [5, 2, 2, 3, 99]}  # unsorted, duplicate, out of range
    }
    interp = validate_and_sanitize_directive(raw_d, 0, sample_battery)
    assert interp.structured_adjustment.hours == [2, 3, 5]
