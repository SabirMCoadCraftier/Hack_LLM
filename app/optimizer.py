import numpy as np
from scipy.optimize import linprog
from typing import List, Dict, Any, Tuple
from app.models import (
    OptimizeEnergyRequest,
    DirectiveInterpretation,
    DirectiveType,
    HourlyPlanEntry,
    BatteryAction,
    OptimizeEnergyResponse
)

def solve_energy_schedule(
    request: OptimizeEnergyRequest,
    directives: List[DirectiveInterpretation]
) -> OptimizeEnergyResponse:
    """
    Formulates and solves the 24-hour energy scheduling Linear Program (LP).
    Minimizes grid import electricity cost while enforcing:
    1. Energy balance: grid + solar_used + discharge = demand + charge
    2. Effective solar usage limits (after solar_reduction)
    3. Battery SoC bounds and rate limits (after minimum_battery_reserve, no_charge, no_discharge)
    4. Grid import caps (max_grid_window)
    5. End-of-day battery neutrality (E_24 == initial_energy)
    6. Peak-smoothing tie-breaker (minimizes peak grid import among equal-cost schedules)
    """
    hours_data = request.hours
    battery = request.battery
    
    # 1. Initialize hourly constraint arrays over 24 hours
    effective_solar = np.array([h.solar_kwh for h in hours_data], dtype=float)
    min_reserve = np.full(24, battery.minimum_energy_kwh, dtype=float)
    max_charge_limit = np.full(24, battery.max_charge_kwh_per_hour, dtype=float)
    max_discharge_limit = np.full(24, battery.max_discharge_kwh_per_hour, dtype=float)
    max_grid_limit = np.full(24, np.inf, dtype=float)

    # 2. Apply active directives to constraint arrays
    for directive in directives:
        if not directive.applies or not directive.structured_adjustment:
            continue
        
        adj = directive.structured_adjustment
        affected_hours = adj.hours
        
        if directive.directive_type == DirectiveType.SOLAR_REDUCTION:
            if adj.factor is not None:
                for h in affected_hours:
                    if 0 <= h < 24:
                        effective_solar[h] = hours_data[h].solar_kwh * adj.factor

        elif directive.directive_type == DirectiveType.MINIMUM_BATTERY_RESERVE:
            if adj.minimum_energy_kwh is not None:
                for h in affected_hours:
                    if 0 <= h < 24:
                        min_reserve[h] = max(min_reserve[h], adj.minimum_energy_kwh)

        elif directive.directive_type == DirectiveType.NO_CHARGE_WINDOW:
            for h in affected_hours:
                if 0 <= h < 24:
                    max_charge_limit[h] = 0.0

        elif directive.directive_type == DirectiveType.NO_DISCHARGE_WINDOW:
            for h in affected_hours:
                if 0 <= h < 24:
                    max_discharge_limit[h] = 0.0

        elif directive.directive_type == DirectiveType.MAX_GRID_WINDOW:
            if adj.max_grid_kwh is not None:
                for h in affected_hours:
                    if 0 <= h < 24:
                        max_grid_limit[h] = min(max_grid_limit[h], adj.max_grid_kwh)

    # 3. Formulate SciPy Linear Program
    # Decision variables (97 total):
    # Index 0..23: G_h (grid_kwh)
    # Index 24..47: S_h (solar_used_kwh)
    # Index 48..71: C_h (charge_kwh)
    # Index 72..95: D_h (discharge_kwh)
    # Index 96: P (peak grid import tie-breaker variable)

    # Objective: Minimize sum(G_h * tariff_h) + 1e-6 * P
    c = np.zeros(97)
    for h in range(24):
        c[h] = hours_data[h].tariff_bdt_per_kwh
    c[96] = 1e-6  # Tiny tie-breaker to minimize peak grid import among equal-cost schedules

    # Equalities A_eq * x = b_eq
    A_eq = []
    b_eq = []

    # Constraint 1: Energy balance: G_h + S_h + D_h - C_h = demand_h for h=0..23
    for h in range(24):
        row = np.zeros(97)
        row[h] = 1.0        # G_h
        row[24 + h] = 1.0   # S_h
        row[48 + h] = -1.0  # C_h
        row[72 + h] = 1.0   # D_h
        A_eq.append(row)
        b_eq.append(hours_data[h].demand_kwh)

    # Constraint 2: End-of-day battery neutrality: E_24 = E_initial => sum(C_k) - sum(D_k) = 0
    row_eod = np.zeros(97)
    row_eod[48:72] = 1.0   # sum(C_k)
    row_eod[72:96] = -1.0  # -sum(D_k)
    A_eq.append(row_eod)
    b_eq.append(0.0)

    # Inequalities A_ub * x <= b_ub
    A_ub = []
    b_ub = []

    # Constraint 3: Battery Energy Bounds at end of each hour h: min_reserve[h] <= E_{h+1} <= capacity
    E_initial = battery.initial_energy_kwh
    capacity = battery.capacity_kwh

    for h in range(24):
        # Upper bound: E_{h+1} <= capacity
        row_ub = np.zeros(97)
        row_ub[48 : 48 + h + 1] = 1.0
        row_ub[72 : 72 + h + 1] = -1.0
        A_ub.append(row_ub)
        b_ub.append(capacity - E_initial)

        # Lower bound: E_{h+1} >= min_reserve[h]
        row_lb = np.zeros(97)
        row_lb[48 : 48 + h + 1] = -1.0
        row_lb[72 : 72 + h + 1] = 1.0
        A_ub.append(row_lb)
        b_ub.append(E_initial - min_reserve[h])

    # Constraint 4: Peak grid import variable P >= G_h  =>  G_h - P <= 0
    for h in range(24):
        row_p = np.zeros(97)
        row_p[h] = 1.0
        row_p[96] = -1.0
        A_ub.append(row_p)
        b_ub.append(0.0)

    # Variable bounds (97 pairs)
    bounds = []
    for h in range(24):
        # G_h bounds
        g_max = max_grid_limit[h] if np.isfinite(max_grid_limit[h]) else None
        bounds.append((0.0, g_max))

    for h in range(24):
        # S_h bounds
        bounds.append((0.0, effective_solar[h]))

    for h in range(24):
        # C_h bounds
        bounds.append((0.0, max_charge_limit[h]))

    for h in range(24):
        # D_h bounds
        bounds.append((0.0, max_discharge_limit[h]))

    # P bound (peak grid import)
    bounds.append((0.0, None))

    # 4. Run SciPy linprog with Highs solver
    res = linprog(
        c,
        A_ub=np.array(A_ub) if A_ub else None,
        b_ub=np.array(b_ub) if b_ub else None,
        A_eq=np.array(A_eq),
        b_eq=np.array(b_eq),
        bounds=bounds,
        method="highs"
    )

    if not res.success:
        raise ValueError(f"Linear program optimization failed: {res.message}")

    x = res.x
    grid_vals = x[0:24]
    solar_used_vals = x[24:48]
    charge_vals = x[48:72]
    discharge_vals = x[72:96]

    # Clean small floating point numerical noise (< 1e-5)
    grid_vals = np.where(grid_vals < 1e-5, 0.0, grid_vals)
    solar_used_vals = np.where(solar_used_vals < 1e-5, 0.0, solar_used_vals)
    charge_vals = np.where(charge_vals < 1e-5, 0.0, charge_vals)
    discharge_vals = np.where(discharge_vals < 1e-5, 0.0, discharge_vals)

    # 5. Build hourly plan entries & track battery state
    hourly_plan: List[HourlyPlanEntry] = []
    current_energy = E_initial
    
    total_grid_kwh = 0.0
    total_cost_bdt = 0.0
    peak_grid_kwh = 0.0

    for h in range(24):
        g = float(grid_vals[h])
        s = float(solar_used_vals[h])
        c_kwh = float(charge_vals[h])
        d_kwh = float(discharge_vals[h])

        if c_kwh > 1e-4:
            action = BatteryAction.CHARGE
            action_kwh = c_kwh
            current_energy += c_kwh
        elif d_kwh > 1e-4:
            action = BatteryAction.DISCHARGE
            action_kwh = d_kwh
            current_energy -= d_kwh
        else:
            action = BatteryAction.IDLE
            action_kwh = 0.0

        # Ensure floating-point rounding precision
        g_round = round(g, 4)
        s_round = round(s, 4)
        action_kwh_round = round(action_kwh, 4)
        energy_after_round = round(current_energy, 4)

        hourly_plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=g_round,
                solar_used_kwh=s_round,
                battery_action=action,
                battery_kwh=action_kwh_round,
                battery_energy_after_kwh=energy_after_round
            )
        )

        total_grid_kwh += g_round
        total_cost_bdt += g_round * hours_data[h].tariff_bdt_per_kwh
        peak_grid_kwh = max(peak_grid_kwh, g_round)

    total_grid_kwh = round(total_grid_kwh, 2)
    total_cost_bdt = round(total_cost_bdt, 2)
    peak_grid_kwh = round(peak_grid_kwh, 2)

    # 6. Generate human-readable plan summary
    summary_parts = []
    active_count = sum(1 for d in directives if d.applies)
    if active_count > 0:
        summary_parts.append(f"Applied {active_count} operator directive(s).")
    else:
        summary_parts.append("No active operator directives affect today's schedule.")

    summary_parts.append(
        f"Optimized schedule minimizes total grid cost to {total_cost_bdt:.2f} BDT "
        f"using {total_grid_kwh:.2f} kWh total grid import with peak import of {peak_grid_kwh:.2f} kWh, "
        f"maintaining end-of-day battery neutrality at {E_initial:.1f} kWh."
    )
    plan_summary = " ".join(summary_parts)

    return OptimizeEnergyResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=directives,
        hourly_plan=hourly_plan,
        total_grid_kwh=total_grid_kwh,
        total_cost_bdt=total_cost_bdt,
        peak_grid_kwh=peak_grid_kwh,
        plan_summary=plan_summary
    )
