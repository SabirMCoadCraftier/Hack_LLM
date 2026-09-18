# GridWise — Smart Campus Energy Optimizer

> **BUP CSE Fest 2026 Hackathon · Online Preliminary Round**  
> **LLM-Assisted Operator Directive Interpretation & Energy Optimization Service**

GridWise is a production-ready HTTP API service built with FastAPI, SciPy, and Pydantic. It translates natural-language operator notes into machine-checkable structured energy directives via an LLM + Guardrail pipeline, formulates a 24-hour Linear Programming (LP) cost minimization model, and returns an optimal hourly energy schedule for campus smart microgrids.

---

## 🏛️ System Architecture & Processing Flow

```
+-----------------------------------------------------------------------------------+
|                                 HTTP Request                                      |
|    POST /optimize-energy { scenario_id, operator_notes, hours, battery }          |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                             1. LLM Interpreter Module                             |
|  Calls LLM (OpenAI / Anthropic / Gemini / Local / Fallback NLP Parser)            |
|  Translates operator_notes -> raw directive JSON                                   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        2. Deterministic Guardrails & Validator                    |
|  - Validate directive types, hour ranges (0..23 ascending), numeric bounds        |
|  - Enforce applies=false for no_op, applies=true for active directives            |
|  - Convert percentage reserves & time window formats                             |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                          3. Linear Programming Optimizer                          |
|  Formulates 24-hour cost minimization LP subject to:                              |
|  - Energy Balance: Grid + Solar_Used + Discharge = Demand + Charge                |
|  - Effective Solar Bounds (after solar_reduction)                                 |
|  - Battery Capacity, Minimum Reserve (after minimum_battery_reserve)              |
|  - Hourly Charge/Discharge Rate Limits & Windows (no_charge / no_discharge)       |
|  - Grid Import Caps (max_grid_window)                                             |
|  - End-of-day Battery Neutrality: E_24 == Initial_Energy                          |
|  - Peak-Smoothing Tie Breaker (minimizes peak grid import among optimal plans)    |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                            4. Recalculator & Formatter                            |
|  - Compute total_grid_kwh, total_cost_bdt, peak_grid_kwh                          |
|  - Generate concise plan_summary                                                  |
|  - Return exact canonical JSON response                                           |
+-----------------------------------------------------------------------------------+
```

---

## ⚡ Key Features & Highlights

1. **Strict Guardrails**: Validates and normalizes directive types (`solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, `no_op`), hours (`0..23` ascending), factor ranges (`0.0..1.0`), and reserve limits.
2. **Offline Reproducibility**: Includes a high-precision rule & NLP parser fallback that ensures 100% functionality even when no LLM API key is configured or during offline judging.
3. **Exact LP Solver**: Solves the 24-hour energy balance and battery state-transition equations using `scipy.optimize.linprog` (HiGHS solver) with machine precision.
4. **End-of-Day Neutrality**: Enforces $E_{24} = E_{\text{initial}}$, ensuring starting battery energy is not depleted as a one-time free source.
5. **Zero-Secret Docker Setup**: Ships with a containerized Dockerfile and docker-compose setup suitable for automated evaluation.

---

## 🛠️ Environment Variables & Configuration

Create a `.env` file or export environment variables:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `HOST` | `0.0.0.0` | Host IP interface to bind Uvicorn |
| `PORT` | `8000` | Port number to expose |
| `LLM_PROVIDER` | `openai` | LLM provider (`openai`, `anthropic`, `gemini`, `local`) |
| `LLM_MODEL` | `gpt-4o-mini` | LLM model identifier |
| `LLM_API_KEY` | `""` | API Key for LLM service (optional; falls back to NLP engine if empty) |
| `LLM_BASE_URL` | `""` | Custom OpenAI-compatible base URL (optional) |
| `SOLVER_TYPE` | `scipy` | Optimization solver backend (`scipy` or `pulp`) |

---

## 🚀 Quickstart & Local Setup

### 1. Prerequisites
- Python 3.10+ installed
- Git & Pip

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/your-repo/gridwise-solution.git
cd gridwise-solution

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Web Service
```bash
python app/main.py
```
Or using Uvicorn directly:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🧪 Testing & Verification

Run the full test suite including health check, guardrail unit tests, optimizer tests, and public sample cases:

```bash
pytest
```

---

## 📡 API Usage & cURL Examples

### 1. Health Readiness Check (`GET /health`)
```bash
curl -X GET http://localhost:8000/health
```
**Response:**
```json
{
  "status": "ok"
}
```

### 2. Energy Optimization (`POST /optimize-energy`)
```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "SAMPLE-01",
    "operator_notes": [
      "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
      "The sports office moved next month registration deadline."
    ],
    "hours": [
      {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 1, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 2, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 3, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 4, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 5, "demand_kwh": 95, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 6, "demand_kwh": 110, "solar_kwh": 5, "tariff_bdt_per_kwh": 8},
      {"hour": 7, "demand_kwh": 130, "solar_kwh": 20, "tariff_bdt_per_kwh": 10},
      {"hour": 8, "demand_kwh": 150, "solar_kwh": 50, "tariff_bdt_per_kwh": 12},
      {"hour": 9, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
      {"hour": 10, "demand_kwh": 175, "solar_kwh": 130, "tariff_bdt_per_kwh": 16},
      {"hour": 11, "demand_kwh": 180, "solar_kwh": 160, "tariff_bdt_per_kwh": 16},
      {"hour": 12, "demand_kwh": 185, "solar_kwh": 180, "tariff_bdt_per_kwh": 15},
      {"hour": 13, "demand_kwh": 180, "solar_kwh": 170, "tariff_bdt_per_kwh": 14},
      {"hour": 14, "demand_kwh": 170, "solar_kwh": 140, "tariff_bdt_per_kwh": 13},
      {"hour": 15, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
      {"hour": 16, "demand_kwh": 170, "solar_kwh": 45, "tariff_bdt_per_kwh": 18},
      {"hour": 17, "demand_kwh": 185, "solar_kwh": 10, "tariff_bdt_per_kwh": 22},
      {"hour": 18, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 28},
      {"hour": 19, "demand_kwh": 215, "solar_kwh": 0, "tariff_bdt_per_kwh": 30},
      {"hour": 20, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 26},
      {"hour": 21, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 18},
      {"hour": 22, "demand_kwh": 135, "solar_kwh": 0, "tariff_bdt_per_kwh": 10},
      {"hour": 23, "demand_kwh": 105, "solar_kwh": 0, "tariff_bdt_per_kwh": 7}
    ],
    "battery": {
      "capacity_kwh": 220,
      "initial_energy_kwh": 110,
      "minimum_energy_kwh": 40,
      "max_charge_kwh_per_hour": 50,
      "max_discharge_kwh_per_hour": 50
    }
  }'
```

---

## 🐳 Docker Deployment & Container Quickstart

### 1. Build Docker Image
```bash
docker build -t gridwise-app .
```

### 2. Run Container
```bash
docker run -d -p 8000:8000 --name gridwise-service gridwise-app
```

### 3. Run with Docker Compose
```bash
docker-compose up --build -d
```

---

## 🔐 Security & Repository Policy

- **No Secrets Committed**: API keys are configured strictly via environment variables or runtime injection. No passwords, private tokens, or credentials exist in source code or docker images.
- **Controlled Failure**: Malformed JSON or invalid directives return clean HTTP 400 / 422 responses without exposing raw stack traces.
