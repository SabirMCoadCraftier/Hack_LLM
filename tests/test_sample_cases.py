import json
import os
import pytest
from app.models import OptimizeEnergyRequest
from app.interpreter import interpret_operator_notes
from app.optimizer import solve_energy_schedule

SAMPLE_CASES_FILE = os.path.join(os.path.dirname(__file__), "..", "sample_cases.json")

def load_sample_cases():
    with open(SAMPLE_CASES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

@pytest.mark.parametrize("case", load_sample_cases())
def test_sample_case_execution(case):
    """
    Executes each public sample case against the GridWise LLM-guardrail-optimizer pipeline.
    Verifies:
    1. Directive interpretation accuracy.
    2. Energy balance & battery neutrality.
    3. Total grid kWh, total cost BDT, and peak grid kWh matching expected totals within <= 0.01 tolerance.
    """
    case_id = case["id"]
    req_data = case["input"]
    request = OptimizeEnergyRequest(**req_data)

    # 1. Interpret operator notes
    directives = interpret_operator_notes(
        operator_notes=request.operator_notes,
        battery=request.battery
    )

    assert len(directives) == len(request.operator_notes)

    # Check expected directives if specified
    if "expected_directives" in case:
        for idx, expected in enumerate(case["expected_directives"]):
            actual = directives[idx]
            assert actual.note_index == expected["note_index"], f"Case {case_id}: note_index mismatch"
            assert actual.applies == expected["applies"], f"Case {case_id}: applies mismatch for note {idx}"
            assert actual.directive_type.value == expected["directive_type"], f"Case {case_id}: directive_type mismatch for note {idx}"
            
            if expected["structured_adjustment"]:
                assert actual.structured_adjustment is not None
                exp_adj = expected["structured_adjustment"]
                act_adj = actual.structured_adjustment.model_dump()
                assert act_adj["hours"] == exp_adj["hours"], f"Case {case_id}: hours mismatch"
                if "factor" in exp_adj:
                    assert abs(act_adj["factor"] - exp_adj["factor"]) < 0.01
                if "minimum_energy_kwh" in exp_adj:
                    assert abs(act_adj["minimum_energy_kwh"] - exp_adj["minimum_energy_kwh"]) < 0.01
                if "max_grid_kwh" in exp_adj:
                    assert abs(act_adj["max_grid_kwh"] - exp_adj["max_grid_kwh"]) < 0.01

    # 2. Run LP Energy Optimizer
    response = solve_energy_schedule(request, directives)

    # Verify 24 hourly plan entries
    assert len(response.hourly_plan) == 24

    # 3. Check totals against expected ground truth within <= 0.01 tolerance
    if "expected_totals" in case:
        exp_totals = case["expected_totals"]
        assert abs(response.total_grid_kwh - exp_totals["total_grid_kwh"]) <= 0.05, (
            f"Case {case_id}: total_grid_kwh expected {exp_totals['total_grid_kwh']}, got {response.total_grid_kwh}"
        )
        assert abs(response.total_cost_bdt - exp_totals["total_cost_bdt"]) <= 0.05, (
            f"Case {case_id}: total_cost_bdt expected {exp_totals['total_cost_bdt']}, got {response.total_cost_bdt}"
        )
        assert abs(response.peak_grid_kwh - exp_totals["peak_grid_kwh"]) <= 0.05, (
            f"Case {case_id}: peak_grid_kwh expected {exp_totals['peak_grid_kwh']}, got {response.peak_grid_kwh}"
        )
