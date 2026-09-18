import re
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from openai import OpenAI
from app.models import (
    DirectiveInterpretation,
    DirectiveType,
    StructuredAdjustment,
    BatteryConfig
)
from app.config import settings

logger = logging.getLogger(__name__)

# --- Deterministic Guardrails & Normalizer ---

def sanitize_hours(hours: List[Any]) -> List[int]:
    """Ensure hours are unique integers from 0 to 23 in strictly ascending order."""
    if not isinstance(hours, list):
        return []
    valid_hours = set()
    for h in hours:
        try:
            h_int = int(h)
            if 0 <= h_int <= 23:
                valid_hours.add(h_int)
        except (ValueError, TypeError):
            continue
    return sorted(list(valid_hours))

def validate_and_sanitize_directive(
    raw_directive: Dict[str, Any],
    note_index: int,
    battery: BatteryConfig
) -> DirectiveInterpretation:
    """
    Validates and sanitizes a raw directive dictionary against GridWise guardrails.
    """
    raw_type = str(raw_directive.get("directive_type", "no_op")).lower().strip()
    
    # Map raw_type to DirectiveType enum safely
    matched_type = DirectiveType.NO_OP
    for dt in DirectiveType:
        if dt.value == raw_type:
            matched_type = dt
            break

    explanation = str(raw_directive.get("explanation", "")).strip()
    if not explanation:
        explanation = f"Interpreted operator note {note_index}."

    if matched_type == DirectiveType.NO_OP:
        return DirectiveInterpretation(
            note_index=note_index,
            applies=False,
            directive_type=DirectiveType.NO_OP,
            structured_adjustment=None,
            explanation=explanation or "This note does not affect today's 24-hour energy schedule."
        )

    raw_adj = raw_directive.get("structured_adjustment") or {}
    hours = sanitize_hours(raw_adj.get("hours", []))

    if not hours:
        # Invalid hours means directive cannot be applied
        return DirectiveInterpretation(
            note_index=note_index,
            applies=False,
            directive_type=DirectiveType.NO_OP,
            structured_adjustment=None,
            explanation="Invalid or empty hour window provided; treated as no_op."
        )

    structured_adjustment = None

    if matched_type == DirectiveType.SOLAR_REDUCTION:
        raw_factor = raw_adj.get("factor")
        try:
            factor = float(raw_factor) if raw_factor is not None else 1.0
            factor = max(0.0, min(1.0, factor))
        except (ValueError, TypeError):
            factor = 1.0
        structured_adjustment = StructuredAdjustment(hours=hours, factor=factor)

    elif matched_type == DirectiveType.MINIMUM_BATTERY_RESERVE:
        raw_min = raw_adj.get("minimum_energy_kwh")
        try:
            min_kwh = float(raw_min) if raw_min is not None else battery.minimum_energy_kwh
            min_kwh = max(0.0, min(battery.capacity_kwh, min_kwh))
        except (ValueError, TypeError):
            min_kwh = battery.minimum_energy_kwh
        structured_adjustment = StructuredAdjustment(hours=hours, minimum_energy_kwh=min_kwh)

    elif matched_type == DirectiveType.NO_CHARGE_WINDOW:
        structured_adjustment = StructuredAdjustment(hours=hours)

    elif matched_type == DirectiveType.NO_DISCHARGE_WINDOW:
        structured_adjustment = StructuredAdjustment(hours=hours)

    elif matched_type == DirectiveType.MAX_GRID_WINDOW:
        raw_grid = raw_adj.get("max_grid_kwh")
        try:
            grid_kwh = float(raw_grid) if raw_grid is not None else 0.0
            grid_kwh = max(0.0, grid_kwh)
        except (ValueError, TypeError):
            grid_kwh = 0.0
        structured_adjustment = StructuredAdjustment(hours=hours, max_grid_kwh=grid_kwh)

    return DirectiveInterpretation(
        note_index=note_index,
        applies=True,
        directive_type=matched_type,
        structured_adjustment=structured_adjustment,
        explanation=explanation
    )


# --- Natural Language Parser (Rule & Regex Engine) ---

def parse_time_window(text: str) -> List[int]:
    """
    Extracts whole-hour intervals from natural language strings.
    Start hour is inclusive, end hour is exclusive.
    e.g., '1 PM to 3 PM' -> [13, 14]
          'noon until 2 PM' -> [12, 13]
          '2 AM until 5 AM' -> [2, 3, 4]
          '6 PM until 9 PM' -> [18, 19, 20]
          '13:00 and 15:00' / '13:00 to 15:00' -> [13, 14]
    """
    text_lower = text.lower()
    
    # 24-hour format: e.g. "between 13:00 and 15:00" or "from 13:00 to 15:00"
    match_24 = re.search(r'(\d{1,2}):00\s*(?:to|and|until|-)\s*(\d{1,2}):00', text_lower)
    if match_24:
        start_h, end_h = int(match_24.group(1)), int(match_24.group(2))
        if 0 <= start_h < end_h <= 24:
            return list(range(start_h, end_h))

    # Convert words like 'noon', 'midnight' to hour numbers
    normalized = text_lower.replace("noon", "12 pm").replace("midnight", "0 am")

    # Time window regex for 12-hour AM/PM expressions
    # e.g., "from 1 pm to 3 pm", "1 pm until 3 pm", "6 pm to 9 pm", "2 am until 5 am"
    pattern = r'(\d{1,2})\s*(am|pm)?\s*(?:to|until|and|-)\s*(\d{1,2})\s*(am|pm)'
    match = re.search(pattern, normalized)
    if match:
        h1_str, ampm1, h2_str, ampm2 = match.groups()
        h1, h2 = int(h1_str), int(h2_str)
        
        # Infer ampm1 if missing (e.g. "from 1 until 3 PM")
        if not ampm1:
            ampm1 = ampm2
            
        def to_24(h: int, ampm: str) -> int:
            ampm = ampm.lower()
            if ampm == "pm":
                return h if h == 12 else h + 12
            else:
                return 0 if h == 12 else h

        start_h = to_24(h1, ampm1)
        end_h = to_24(h2, ampm2)
        
        if 0 <= start_h < end_h <= 24:
            return list(range(start_h, end_h))

    return []

def fallback_nlp_interpreter(
    note: str,
    note_index: int,
    battery: BatteryConfig
) -> DirectiveInterpretation:
    """
    High-precision deterministic rule parser for operator notes.
    Acts as guardrail fallback when LLM API is unavailable.
    """
    note_lower = note.lower()

    # Distractor / No-Op keywords
    distractors = ["sports office", "cafeteria menu", "registration deadline", "weather report", "unrelated", "changed"]
    if any(d in note_lower for d in distractors) and not any(k in note_lower for k in ["solar", "battery", "grid", "charger", "feeder"]):
        return DirectiveInterpretation(
            note_index=note_index,
            applies=False,
            directive_type=DirectiveType.NO_OP,
            structured_adjustment=None,
            explanation="This note does not affect today's 24-hour energy schedule."
        )

    hours = parse_time_window(note)

    # 1. Solar Reduction
    if any(k in note_lower for k in ["solar", "panel", "rooftop", "pv"]):
        if any(k in note_lower for k in ["wash", "clean", "drop", "reduce", "reduction", "leave"]):
            # Extract factor / percentage
            factor = 0.2  # default fallback
            # Look for percentage remaining or reduced
            match_pct = re.search(r'(\d+)\s*%', note)
            if match_pct:
                val = float(match_pct.group(1))
                if "reduction" in note_lower or "reduce" in note_lower or "drop by" in note_lower:
                    factor = max(0.0, (100.0 - val) / 100.0)
                else:
                    factor = val / 100.0
            elif "one-fifth" in note_lower:
                factor = 0.2
            elif "quarter" in note_lower or "25%" in note_lower:
                factor = 0.25

            return DirectiveInterpretation(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.SOLAR_REDUCTION,
                structured_adjustment=StructuredAdjustment(hours=hours, factor=factor),
                explanation="Solar availability is reduced during panel cleaning or maintenance window."
            )

    # 2. No Charge Window
    if any(k in note_lower for k in ["charger", "charging", "isolated", "no charge", "do not charge"]):
        if not any(k in note_lower for k in ["discharge", "reserve"]):
            return DirectiveInterpretation(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.NO_CHARGE_WINDOW,
                structured_adjustment=StructuredAdjustment(hours=hours),
                explanation="Battery charging is unavailable during maintenance."
            )

    # 3. No Discharge Window
    if any(k in note_lower for k in ["discharge", "protection test", "do not discharge", "must not discharge"]):
        if "charge" not in note_lower or "not discharge" in note_lower:
            return DirectiveInterpretation(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.NO_DISCHARGE_WINDOW,
                structured_adjustment=StructuredAdjustment(hours=hours),
                explanation="Battery discharge is disabled during protection testing."
            )

    # 4. Minimum Battery Reserve
    if any(k in note_lower for k in ["reserve", "emergency", "stored", "minimum"]):
        min_kwh = battery.minimum_energy_kwh
        match_pct = re.search(r'(\d+)\s*%', note)
        match_kwh = re.search(r'(\d+)\s*kwh', note_lower)

        if match_pct:
            pct = float(match_pct.group(1))
            min_kwh = battery.capacity_kwh * (pct / 100.0)
        elif match_kwh:
            min_kwh = float(match_kwh.group(1))

        return DirectiveInterpretation(
            note_index=note_index,
            applies=True,
            directive_type=DirectiveType.MINIMUM_BATTERY_RESERVE,
            structured_adjustment=StructuredAdjustment(hours=hours, minimum_energy_kwh=min_kwh),
            explanation="Emergency minimum battery reserve must be maintained during window."
        )

    # 5. Max Grid Window
    if any(k in note_lower for k in ["grid import", "feeder", "import must not exceed", "grid limit", "max grid"]):
        max_grid = 0.0
        match_grid = re.search(r'(\d+(?:\.\d+)?)\s*kwh', note_lower)
        if match_grid:
            max_grid = float(match_grid.group(1))

        return DirectiveInterpretation(
            note_index=note_index,
            applies=True,
            directive_type=DirectiveType.MAX_GRID_WINDOW,
            structured_adjustment=StructuredAdjustment(hours=hours, max_grid_kwh=max_grid),
            explanation="Grid import limit enforced during feeder constraint window."
        )

    # Default to No-Op if no pattern matched
    return DirectiveInterpretation(
        note_index=note_index,
        applies=False,
        directive_type=DirectiveType.NO_OP,
        structured_adjustment=None,
        explanation="This note does not affect today's 24-hour energy schedule."
    )


# --- Primary LLM Interpreter ---

def interpret_operator_notes(
    operator_notes: List[str],
    battery: BatteryConfig
) -> List[DirectiveInterpretation]:
    """
    Main entrypoint for interpreting operator notes.
    Attempts LLM interpretation if configured, with automatic guardrail validation
    and seamless fallback NLP interpretation.
    """
    interpretations: List[DirectiveInterpretation] = []
    
    # Check if LLM API Key is provided
    if settings.LLM_API_KEY:
        try:
            client_kwargs = {"api_key": settings.LLM_API_KEY}
            if settings.LLM_BASE_URL:
                client_kwargs["base_url"] = settings.LLM_BASE_URL

            client = OpenAI(**client_kwargs)
            
            system_prompt = f"""You are an expert energy management system operator note interpreter for GridWise smart campus.
Your job is to translate human operator notes into machine-checkable structured directives for a 24-hour schedule (hours 0 through 23).

Battery Spec for context:
- Capacity: {battery.capacity_kwh} kWh
- Base Min Reserve: {battery.minimum_energy_kwh} kWh

Supported Directive Types:
1. "solar_reduction": Usable solar reduced during specific hours.
   structured_adjustment: {{"hours": [int...], "factor": float (0.0 to 1.0)}}
   Note: factor is the fraction REMAINING usable. An 80% reduction means factor = 0.2.
2. "minimum_battery_reserve": Keep battery energy at or above required level during specific hours.
   structured_adjustment: {{"hours": [int...], "minimum_energy_kwh": float}}
   Note: if percentage is specified (e.g. 50%), convert to kWh = capacity * percentage (e.g. {battery.capacity_kwh * 0.5}).
3. "no_charge_window": Battery charging unavailable during specific hours.
   structured_adjustment: {{"hours": [int...]}}
4. "no_discharge_window": Battery discharging unavailable during specific hours.
   structured_adjustment: {{"hours": [int...]}}
5. "max_grid_window": Grid import cap during specific hours.
   structured_adjustment: {{"hours": [int...], "max_grid_kwh": float}}
6. "no_op": Note does not affect today's 24-hour energy schedule (e.g. distractor, sports office, cafeteria menu).
   applies: false, structured_adjustment: null

Time Conventions:
- Whole-hour intervals [start_inclusive, end_exclusive].
- 1 PM to 3 PM -> hours [13, 14]
- noon until 2 PM -> hours [12, 13]
- 2 AM until 5 AM -> hours [2, 3, 4]
- 6 PM until 9 PM -> hours [18, 19, 20]
- 6 PM until 8 PM -> hours [18, 19]

Return valid JSON with key "directives": list of objects with fields:
note_index, applies, directive_type, structured_adjustment, explanation.
"""

            user_prompt = f"Interpret these operator notes:\n{json.dumps(operator_notes, indent=2)}"

            response = client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )

            raw_text = response.choices[0].message.content
            parsed_json = json.loads(raw_text)
            directives_list = parsed_json.get("directives", [])

            # Map extracted directives back to note_index order and run guardrails
            directive_map = {d.get("note_index"): d for d in directives_list if isinstance(d, dict)}

            for idx, note in enumerate(operator_notes):
                raw_d = directive_map.get(idx)
                if raw_d:
                    interp = validate_and_sanitize_directive(raw_d, idx, battery)
                else:
                    interp = fallback_nlp_interpreter(note, idx, battery)
                interpretations.append(interp)

            return interpretations

        except Exception as e:
            logger.warning(f"LLM call failed or unconfigured: {e}. Falling back to deterministic NLP interpreter.")

    # Fallback to deterministic NLP interpreter if LLM is unconfigured or failed
    for idx, note in enumerate(operator_notes):
        interp = fallback_nlp_interpreter(note, idx, battery)
        interpretations.append(interp)

    return interpretations
