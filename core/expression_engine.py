"""
core/expression_engine.py
=========================
Safe expression evaluator for rule conditions and quantity formulas.

Uses ``simpleeval`` (AST-walking evaluator) to replace all raw ``eval()``
calls in the codebase.  Provides three public helpers:

    evaluate_condition(condition_str, context)  → bool
    evaluate_formula(formula_str, context)      → float
    validate_expression(expr_str, allowed_names) → (bool, str)

The custom ``ExpressionError`` carries a human-friendly message *and* a
closest-match ``suggestion`` when a name is not found.
"""

from __future__ import annotations

import difflib
import math
from typing import Any

from simpleeval import EvalWithCompoundTypes, NameNotDefined

# ─── Iron weight constants (kg per metre) ─────────────────────────────────────
# These are used in formula expressions throughout the ruleset.
IRON_CONSTANTS: dict[str, float] = {
    "CH_75X40":    6.8,
    "CH_100X50":   9.8,
    "ANG_65X65X6": 5.8,
    "ANG_50X50X6": 4.5,
    "FLAT_65X6":   3.1,
    "FLAT_50X6":   2.5,
    "GIWIRE_5MM":  0.123,
    "GIWIRE_4MM":  0.100,
}

# ─── Safe builtins available to all expressions ──────────────────────────────
_SAFE_FUNCTIONS: dict[str, Any] = {
    "int":   int,
    "round": round,
    "abs":   abs,
    "float": float,
    "math":  math,
}


# ─── Custom exception ────────────────────────────────────────────────────────

class ExpressionError(Exception):
    """Raised when a condition or formula cannot be evaluated.

    Attributes
    ----------
    suggestion : str | None
        If the error was caused by an unknown variable name, this holds
        the closest known property name (via ``difflib.get_close_matches``).
    """

    def __init__(self, message: str, suggestion: str | None = None):
        self.suggestion = suggestion
        if suggestion:
            message = f"{message}  (did you mean '{suggestion}'?)"
        super().__init__(message)


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _suggest(name: str, known: list[str]) -> str | None:
    """Return the single closest match for *name* in *known*, or None."""
    matches = difflib.get_close_matches(name, known, n=1, cutoff=0.5)
    return matches[0] if matches else None


def _build_names(context: dict) -> dict:
    """Merge context + iron constants + safe builtins into one namespace."""
    ns: dict[str, Any] = {}
    try:
        from core import db_gateway as _dbg
        sections = _dbg.get_sections()   # cached — no per-call DB hit
        dyn_constants = {code: data["kg_per_metre"] for code, data in sections.items()}
    except Exception:
        dyn_constants = IRON_CONSTANTS
    ns.update(dyn_constants)
    ns.update(context)
    return ns


def _build_functions() -> dict:
    """Return the function namespace for simpleeval."""
    return dict(_SAFE_FUNCTIONS)


# ─── Reused evaluator + parsed-AST cache ──────────────────────────────────────
# Building an EvalWithCompoundTypes and re-parsing the expression string on
# every call dominated refresh time (each rule condition/formula is evaluated
# once per canvas item). We keep ONE evaluator (single-threaded GUI) and swap
# its namespace per call, and cache each expression's parsed AST so identical
# rule strings are parsed only once for the whole session.
_EVALUATOR: "EvalWithCompoundTypes | None" = None
_AST_CACHE: dict[str, Any] = {}


def _evaluator() -> EvalWithCompoundTypes:
    global _EVALUATOR
    if _EVALUATOR is None:
        _EVALUATOR = EvalWithCompoundTypes(names={}, functions=_build_functions())
    return _EVALUATOR


def _parsed(expr: str):
    node = _AST_CACHE.get(expr)
    if node is None:
        node = EvalWithCompoundTypes.parse(expr)
        _AST_CACHE[expr] = node
    return node


# ─── Public API ───────────────────────────────────────────────────────────────

def evaluate_condition(condition_str: str, context: dict) -> bool:
    """Safely evaluate a condition string against *context*.

    Returns ``True`` for empty or ``"True"`` conditions.
    Raises ``ExpressionError`` with a closest-name suggestion on failure.
    """
    if not condition_str or condition_str.strip() in ("", "True"):
        return True
    try:
        evaluator = _evaluator()
        evaluator.names = _build_names(context)
        result = evaluator.eval(condition_str, previously_parsed=_parsed(condition_str))
        return bool(result)
    except NameNotDefined as exc:
        bad_name = str(exc).split("'")[1] if "'" in str(exc) else str(exc)
        suggestion = _suggest(bad_name, list(context.keys()))
        raise ExpressionError(
            f"Unknown name '{bad_name}' in condition",
            suggestion=suggestion,
        ) from exc
    except Exception as exc:
        raise ExpressionError(f"Condition error: {exc}") from exc


def evaluate_formula(formula_str: str, context: dict) -> float:
    """Safely evaluate a quantity formula against *context*.

    Returns ``0.0`` for empty formulas.
    Raises ``ExpressionError`` on failure.
    """
    if not formula_str or formula_str.strip() == "":
        return 0.0
    try:
        evaluator = _evaluator()
        evaluator.names = _build_names(context)
        result = evaluator.eval(formula_str, previously_parsed=_parsed(formula_str))
        return float(result)
    except NameNotDefined as exc:
        bad_name = str(exc).split("'")[1] if "'" in str(exc) else str(exc)
        suggestion = _suggest(bad_name, list(context.keys()) + list(IRON_CONSTANTS.keys()))
        raise ExpressionError(
            f"Unknown name '{bad_name}' in formula",
            suggestion=suggestion,
        ) from exc
    except Exception as exc:
        raise ExpressionError(f"Formula error: {exc}") from exc


def validate_expression(expr_str: str, allowed_names: list[str]) -> tuple[bool, str]:
    """Syntax-check an expression and verify all referenced names are known.

    Parameters
    ----------
    expr_str : str
        The condition or formula expression to validate.
    allowed_names : list[str]
        Property names that are valid in the current context.

    Returns
    -------
    (ok, message)
        ``(True, "")`` on success, ``(False, "descriptive error")`` on failure.
    """
    text = (expr_str or "").strip()
    if not text or text == "True":
        return True, ""

    # 1. Syntax check via compile()
    try:
        code = compile(text, "<expression>", "eval")
    except SyntaxError as e:
        col = f", col {e.offset}" if e.offset else ""
        return False, f"Syntax error: {e.msg}{col}"

    # 2. Extract referenced names from the compiled code object
    all_known = set(allowed_names) | set(IRON_CONSTANTS) | set(_SAFE_FUNCTIONS) | {"True", "False", "None", "and", "or", "not", "in"}
    # code.co_names contains all name references in the expression
    for name in code.co_names:
        if name not in all_known:
            suggestion = _suggest(name, list(all_known))
            hint = f"  Did you mean '{suggestion}'?" if suggestion else ""
            return False, f"Unknown name '{name}'.{hint}"

    return True, ""
