# Execution Plan: GridWise Smart Campus Energy Optimizer

This document breaks down the implementation into incremental, testable tasks.

---

## Task Checklist

- [ ] **Task 1: Project Setup & Data Schemas**
  - Create `requirements.txt` with FastAPI, uvicorn, scipy, pulp, pydantic, openai, pytest, etc.
  - Create `app/config.py` for environment variables and model settings.
  - Create `app/models.py` for request and response Pydantic models matching canonical GridWise schemas.

- [ ] **Task 2: Mathematical LP Optimizer Module (`app/optimizer.py`)**
  - Implement 24-hour Linear Programming energy scheduling model using SciPy / PuLP.
  - Formulate objective function: minimize $\sum_{h=0}^{23} (\text{grid\_kwh}_h \times \text{tariff}_h)$.
  - Enforce constraints:
    - Energy Balance: $\text{grid}_h + \text{solar\_used}_h + \text{discharge}_h = \text{demand}_h + \text{charge}_h$
    - Effective solar limit: $\text{solar\_used}_h \le \text{solar}_h \times \text{factor}_h$
    - Battery state transitions: $E_{h+1} = E_h + \text{charge}_h - \text{discharge}_h$
    - Battery reserve & capacity: $\text{min\_reserve}_h \le E_{h+1} \le \text{capacity}$
    - Charge / discharge hourly rate limits & window exclusions
    - Grid import caps ($\text{grid}_h \le \text{max\_grid\_kwh}$)
    - End-of-day neutrality: $E_{24} = \text{initial\_energy}$
  - Implement recalculation of totals (`total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh`) and `plan_summary` generation.

- [ ] **Task 3: Operator Note Interpreter & Guardrail Engine (`app/interpreter.py`)**
  - Implement natural language time window parser (e.g. "1 PM to 3 PM" -> `[13, 14]`, "noon until 2 PM" -> `[12, 13]`, "6 PM to 9 PM" -> `[18, 19, 20]`).
  - Implement percentage reserve & factor normalizer (e.g. 50% reserve -> `capacity * 0.5`, 80% reduction -> `factor = 0.2`).
  - Implement LLM directive extraction (OpenAI API / LLM provider) with fallback NLP rule engine for offline/unauthenticated execution.
  - Implement deterministic guardrails: validate `directive_type`, `applies` boolean semantics, sorted unique hours 0..23, numeric bounds.

- [ ] **Task 4: FastAPI Web Service (`app/main.py`)**
  - Implement `GET /health` endpoint returning `{"status": "ok"}`.
  - Implement `POST /optimize-energy` endpoint linking interpreter, guardrails, and optimizer.
  - Implement error handling for 400 (malformed JSON/invalid schema), 422 (unsupported inputs), and 500 (safe internal error without secrets/stack trace leaks).

- [ ] **Task 5: Test Suite & Sample Case Verification (`tests/`)**
  - Add `sample_cases.json` containing the 10 public sample cases.
  - Create `tests/test_api.py` for endpoint contracts and health checks.
  - Create `tests/test_interpreter.py` for directive extraction and guardrails.
  - Create `tests/test_optimizer.py` for LP solver correctness and constraints.
  - Create `tests/test_sample_cases.py` to run all 10 sample cases against the API and verify <= 0.01 tolerance on totals and costs.

- [ ] **Task 6: Containerization (`Dockerfile`, `docker-compose.yml`)**
  - Create production-ready `Dockerfile` exposing port 8000 and binding Uvicorn to `0.0.0.0`.
  - Create `docker-compose.yml` for single-command deployment.
  - Create `.dockerignore` for clean builds.

- [ ] **Task 7: Documentation (`README.md`)**
  - Write detailed `README.md` with:
    - Setup & local quickstart instructions
    - Environment variable configuration
    - System architecture diagram & flow description
    - Solver details & guardrail validation explanation
    - `curl` test commands for `/health` and `/optimize-energy`
    - Dependencies, limitations, and secret handling.

- [ ] **Task 8: End-to-End Verification & Walkthrough Artifact**
  - Execute test suite and verify 100% pass rate across all sample cases.
  - Create `walkthrough.md` summarizing system performance, architecture, and verification results.
