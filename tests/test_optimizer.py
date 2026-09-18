import pytest
from app.models import (
    OptimizeEnergyRequest,
    HourEntry,
    BatteryConfig,
    DirectiveInterpretation,
    DirectiveType,
    StructuredAdjustment
)
from app.optimizer import solve_energy_schedule

@pytest.fixture
def base_request():
    return OptimizeEnergyRequest(
        scenario_id="OPT-TEST",
        operator_notes=["No special notes"],
        hours=[
            HourEntry(
                hour=h,
                demand_kwh=100.0,
                solar_kwh=50.0 if 10 <= h <= 15 else 0.0,
                tariff_bdt_per_kwh=10.0 if 17 <= h <= 20 else 5.0
            )
            for h in range(24)
        ],
        battery=BatteryConfig(
            capacity_kwh=200.0,
            initial_energy_kwh=100.0,
            minimum_energy_kwh=40.0,
            max_charge_kwh_per_hour=50.0,
            max_discharge_kwh_per_hour=50.0
        )
    )

def test_energy_balance_and_eod_neutrality(base_request):
    directives = [
        DirectiveInterpretation(
            note_index=0,
            applies=False,
            directive_type=DirectiveType.NO_OP,
            structured_adjustment=None,
            explanation="No op"
        )
    ]
    res = solve_energy_schedule(base_request, directives)
    
    assert len(res.hourly_plan) == 24
    # Verify EOD battery neutrality: E_24 == E_initial
    assert abs(res.hourly_plan[-1].battery_energy_after_kwh - base_request.battery.initial_energy_kwh) < 0.01

    # Verify energy balance for each hour: grid + solar_used + discharge = demand + charge
    for entry in res.hourly_plan:
        charge = entry.battery_kwh if entry.battery_action.value == "charge" else 0.0
        discharge = entry.battery_kwh if entry.battery_action.value == "discharge" else 0.0
        demand = base_request.hours[entry.hour].demand_kwh
        
        balance_left = entry.grid_kwh + entry.solar_used_kwh + discharge
        balance_right = demand + charge
        assert abs(balance_left - balance_right) < 0.01
