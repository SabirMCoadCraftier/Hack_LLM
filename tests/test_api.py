import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check():
    """Verify GET /health returns HTTP 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_optimize_energy_sample_01():
    """Verify POST /optimize-energy processes sample request correctly."""
    sample_request = {
        "scenario_id": "TEST-01",
        "operator_notes": [
            "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
            "The sports office moved next month's registration deadline."
        ],
        "hours": [
            {"hour": h, "demand_kwh": 100 + h * 2, "solar_kwh": 20 if 6 <= h <= 18 else 0, "tariff_bdt_per_kwh": 5 + (h % 5)}
            for h in range(24)
        ],
        "battery": {
            "capacity_kwh": 200,
            "initial_energy_kwh": 100,
            "minimum_energy_kwh": 40,
            "max_charge_kwh_per_hour": 50,
            "max_discharge_kwh_per_hour": 50
        }
    }
    
    response = client.post("/optimize-energy", json=sample_request)
    assert response.status_code == 200
    data = response.json()

    assert data["scenario_id"] == "TEST-01"
    assert len(data["directive_interpretation"]) == 2
    assert len(data["hourly_plan"]) == 24
    assert "total_grid_kwh" in data
    assert "total_cost_bdt" in data
    assert "peak_grid_kwh" in data
    assert "plan_summary" in data

def test_malformed_request():
    """Verify 400 Bad Request on invalid payload."""
    response = client.post("/optimize-energy", json={"invalid": "payload"})
    assert response.status_code == 400
