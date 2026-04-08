# Future Feature Backlog

Captured on: 2026-04-08

## 1) Externalize Conversion Rate
- Move conversion-rate logic/config to an external config source.
- Make values editable without code changes.

## 2) Externalize Iron Variables for Rule Engine
- Move iron-related variables/aliases to external configuration.
- Ensure rule engine and formula builder both read the same source.

## 3) Externalize Iron Calculation
- Move iron calculation formulas/logic to external, user-manageable definitions.
- Keep calculation pipeline deterministic and validated.

## 4) Conductor and DTR Augmentation
- Add augmentation controls for conductor calculations.
- Add augmentation controls for DTR calculations.
- Clarify where augmentation applies (estimate view, exports, rule context).

## 5) Save Project Bundle (Single Action)
- Add one option to save PDF + Excel + drawing JSON together.
- Prefer a single folder output with consistent naming.

## 6) Reuse Last Export Path
- Remember and reuse the last-used directory for document exports.
- Apply to PDF and Excel export flows.

## 7) External, User-Manageable Property Containers
- Move hardcoded object property options to external definitions.
- Example: Pole type values (PCC/STP/RAIL) and nested values (8 mtr/9 mtr) should be editable.
- Allow user to add custom options (example: XYZ with 10 mtr) without code changes.
- Apply the same pattern across all supported object types.

## 8) Recipe-Based Iron Calculation
- Introduce a recipe system for iron calculations.
- Make recipes user-manageable and usable as default actions.
- Support versioned defaults and safe fallback behavior.

## Suggested Implementation Order
1. Reuse last export path.
2. Save project bundle.
3. External property containers.
4. Externalize iron variables and conversion rate.
5. Recipe-based iron calculation.
6. Externalize full iron calculation.
7. Conductor and DTR augmentation.

## Progress
- Implemented on 2026-04-08:
  - Reuse last export path.
  - Save project bundle (PDF + Excel + drawing JSON).
  - Initial custom property system: Property Editor, slot count, per-object Custom 1..N selectors, rule-context exposure, and project save/load persistence.