import json
import httpx
import sys

API_URL = "http://localhost:8000/optimize-energy"
SAMPLE_CASES_FILE = "sample_cases.json"

def main():
    print("=" * 70)
    print("      GridWise API Verification -- Sample Cases Runner")
    print("=" * 70)

    try:
        with open(SAMPLE_CASES_FILE, "r", encoding="utf-8") as f:
            cases = json.load(f)
    except Exception as e:
        print(f"Error loading {SAMPLE_CASES_FILE}: {e}")
        sys.exit(1)

    print(f"Loaded {len(cases)} sample cases from {SAMPLE_CASES_FILE}.\n")

    passed_count = 0
    client = httpx.Client(timeout=10.0)

    for idx, case in enumerate(cases, 1):
        case_id = case.get("id", f"Case-{idx}")
        label = case.get("label", "Sample Case")
        payload = case.get("input")

        print(f"[{idx}/{len(cases)}] Testing {case_id}: {label}...")
        
        try:
            response = client.post(API_URL, json=payload)
            if response.status_code != 200:
                print(f"   [FAIL] Failed with HTTP {response.status_code}: {response.text}")
                continue

            data = response.json()
            total_grid = data.get("total_grid_kwh")
            total_cost = data.get("total_cost_bdt")
            peak_grid = data.get("peak_grid_kwh")
            directives = data.get("directive_interpretation", [])

            print(f"   [OK] HTTP 200 OK")
            print(f"   - Scenario ID: {data.get('scenario_id')}")
            print(f"   - Interpreted Directives: {len(directives)}")
            for d in directives:
                dtype = d.get("directive_type")
                applies = d.get("applies")
                print(f"     * Note {d.get('note_index')}: {dtype} (applies={applies})")
            print(f"   - Total Grid kWh: {total_grid}")
            print(f"   - Total Cost BDT: {total_cost}")
            print(f"   - Peak Grid kWh:  {peak_grid}")

            if "expected_totals" in case:
                exp = case["expected_totals"]
                print(f"   - Expected: Cost={exp.get('total_cost_bdt')}, Grid={exp.get('total_grid_kwh')}, Peak={exp.get('peak_grid_kwh')}")

            passed_count += 1
            print("-" * 70)

        except httpx.ConnectError:
            print(f"   [FAIL] Connection Error: Could not connect to API at {API_URL}.")
            print("   Make sure the server is running (`py app/main.py` or `py -m uvicorn app.main:app`).")
            sys.exit(1)
        except Exception as e:
            print(f"   [FAIL] Error: {e}")
            print("-" * 70)

    print(f"\nSummary: {passed_count}/{len(cases)} sample cases successfully verified against GridWise API!")

if __name__ == "__main__":
    main()
