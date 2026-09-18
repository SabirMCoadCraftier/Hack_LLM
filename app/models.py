from typing import List, Optional, Union
from enum import Enum
from pydantic import BaseModel, Field, field_validator

class DirectiveType(str, Enum):
    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"

class BatteryAction(str, Enum):
    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"

# --- Request Models ---

class HourEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0-23)")
    demand_kwh: float = Field(..., ge=0, description="Campus demand in kWh")
    solar_kwh: float = Field(..., ge=0, description="Rooftop solar forecast in kWh")
    tariff_bdt_per_kwh: float = Field(..., ge=0, description="Grid tariff in BDT per kWh")

class BatteryConfig(BaseModel):
    capacity_kwh: float = Field(..., gt=0, description="Maximum battery capacity in kWh")
    initial_energy_kwh: float = Field(..., ge=0, description="Starting battery energy level in kWh")
    minimum_energy_kwh: float = Field(..., ge=0, description="Base minimum battery reserve level in kWh")
    max_charge_kwh_per_hour: float = Field(..., ge=0, description="Maximum hourly battery charging rate in kWh")
    max_discharge_kwh_per_hour: float = Field(..., ge=0, description="Maximum hourly battery discharging rate in kWh")

class OptimizeEnergyRequest(BaseModel):
    scenario_id: str = Field(..., description="Unique scenario identifier")
    operator_notes: List[str] = Field(..., min_length=1, max_length=3, description="Operator natural-language notes")
    hours: List[HourEntry] = Field(..., min_length=24, max_length=24, description="24 hourly entries")
    battery: BatteryConfig = Field(..., description="Battery specs")

    @field_validator("hours")
    @classmethod
    def validate_hours(cls, v: List[HourEntry]) -> List[HourEntry]:
        hour_indices = [h.hour for h in v]
        if sorted(hour_indices) != list(range(24)):
            raise ValueError("hours array must contain exactly 24 unique entries for hours 0 through 23")
        return v

# --- Response Models ---

class StructuredAdjustment(BaseModel):
    hours: List[int] = Field(..., description="List of affected hours (unique, ascending 0-23)")
    factor: Optional[float] = Field(default=None, description="Usable solar fraction remaining (for solar_reduction)")
    minimum_energy_kwh: Optional[float] = Field(default=None, description="Required reserve energy in kWh (for minimum_battery_reserve)")
    max_grid_kwh: Optional[float] = Field(default=None, description="Maximum grid import cap in kWh (for max_grid_window)")

class DirectiveInterpretation(BaseModel):
    note_index: int = Field(..., ge=0, description="Zero-based index of corresponding operator note")
    applies: bool = Field(..., description="True for active directives, false only for no_op")
    directive_type: DirectiveType = Field(..., description="Interpreted directive type")
    structured_adjustment: Optional[StructuredAdjustment] = Field(default=None, description="Structured parameters (null for no_op)")
    explanation: str = Field(..., description="Human-readable rationale for interpretation")

class HourlyPlanEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0-23)")
    grid_kwh: float = Field(..., ge=0, description="Grid import energy purchased in kWh")
    solar_used_kwh: float = Field(..., ge=0, description="Solar energy utilized in kWh")
    battery_action: BatteryAction = Field(..., description="Battery action (charge, discharge, idle)")
    battery_kwh: float = Field(..., ge=0, description="Battery action energy magnitude in kWh")
    battery_energy_after_kwh: float = Field(..., ge=0, description="Battery energy state immediately after completing this hour in kWh")

class OptimizeEnergyResponse(BaseModel):
    scenario_id: str = Field(..., description="Echo of scenario_id")
    directive_interpretation: List[DirectiveInterpretation] = Field(..., description="Array of interpretations in note_index order")
    hourly_plan: List[HourlyPlanEntry] = Field(..., min_length=24, max_length=24, description="24-hour schedule")
    total_grid_kwh: float = Field(..., ge=0, description="Sum of grid import across all 24 hours")
    total_cost_bdt: float = Field(..., ge=0, description="Total grid electricity cost in BDT")
    peak_grid_kwh: float = Field(..., ge=0, description="Maximum hourly grid import in kWh")
    plan_summary: str = Field(..., description="Short explanation of final operational strategy")

class HealthResponse(BaseModel):
    status: str = "ok"
