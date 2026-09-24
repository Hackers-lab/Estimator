"""
canvas/canvas_ops.py
====================
Provides pure-logic graph traversal, node connection validation,
and spatial node query helpers for canvas operations.
"""
from __future__ import annotations
import math
from typing import Any, List, Optional, Tuple, Set


def is_ht_node(node: Any) -> bool:
    """
    Returns True if a node is effectively HT.
    SmartStructure is always HT.
    SmartPole: uses its voltage type (pole_type).
    SmartConsumer: always LT.
    """
    from canvas.nodes import SmartStructure
    from canvas._base import SmartPole

    if isinstance(node, SmartStructure):
        return True
    if isinstance(node, SmartPole):
        if getattr(node, "is_existing", False):
            return getattr(node, "existing_subtype", "LT") != "LT"
        return getattr(node, "pole_type", "LT") == "HT"
    return False


def get_node_voltage(node: Any) -> str:
    """Determine effective voltage level for a canvas node."""
    from canvas.nodes import SmartStructure
    from canvas._base import SmartPole

    if isinstance(node, SmartStructure):
        return "BRIDGE"
    if isinstance(node, SmartPole):
        if getattr(node, "is_existing", False):
            sub = getattr(node, "existing_subtype", "LT")
            if sub == "33":
                return "33kV"
            if sub in ("HT", "DP", "TP", "4P", "DTR"):
                return "11kV"
            return "LT"
        v = getattr(node, "voltage_level", None)
        if v:
            return v
        return "11kV" if getattr(node, "pole_type", "LT") == "HT" else "LT"
    return "LT"


def active_connected_spans(node: Any) -> List[Any]:
    """Return all currently active and placed spans connected to node."""
    return [s for s in getattr(node, "connected_spans", []) if s is not None and s.scene() is not None]


def span_other_endpoint(span: Any, node: Any) -> Optional[Any]:
    """Given a span and one endpoint node, return the opposite node."""
    if span.p1 == node:
        return span.p2
    if span.p2 == node:
        return span.p1
    return None


def span_exists_between(p1: Any, p2: Any) -> bool:
    """Check if an active span already exists directly between p1 and p2."""
    for s in active_connected_spans(p1):
        if (s.p1 == p1 and s.p2 == p2) or (s.p1 == p2 and s.p2 == p1):
            return True
    return False


def has_path_between(start: Any, target: Any) -> bool:
    """Breadth-first search to check if a connected path exists between start and target."""
    if start == target:
        return True
    visited: Set[Any] = {start}
    queue: List[Any] = [start]
    while queue:
        node = queue.pop(0)
        for span in active_connected_spans(node):
            other = span_other_endpoint(span, node)
            if other is None:
                continue
            if other == target:
                return True
            if other not in visited:
                visited.add(other)
                queue.append(other)
    return False


def validate_span_creation(p1: Any, p2: Any) -> Tuple[bool, str]:
    """
    Validate whether a span between p1 and p2 is legal.
    Rules:
    - Must be different nodes.
    - No duplicate spans.
    - No loops (tree topology).
    - 33kV cannot connect directly to 11kV or LT without DTR Substation.
    """
    if p1 == p2:
        return False, "Start and end node must be different."
    if span_exists_between(p1, p2):
        return False, "A span already exists between these two nodes."
    if has_path_between(p1, p2):
        return False, "This connection would create a loop."

    v1, v2 = get_node_voltage(p1), get_node_voltage(p2)
    if (v1 == "33kV" and v2 in ("11kV", "LT")) or (v2 == "33kV" and v1 in ("11kV", "LT")):
        return False, "33kV lines cannot connect directly to 11kV or LT nodes. Use a DTR Substation to step down voltage."

    return True, ""


def find_nearby_node(nodes: List[Any], x: float, y: float, min_gap: float = 20.0) -> Optional[Any]:
    """Find if any existing node is within min_gap distance of (x, y)."""
    for node in nodes:
        if math.hypot(node.x() - x, node.y() - y) < min_gap:
            return node
    return None


def recalculate_span_types(scene_items: List[Any]) -> None:
    """
    Propagation logic: spans between two effectively-existing endpoints
    become existing spans (no BOM contribution).
    """
    from canvas._base import SmartPole
    from canvas.nodes import SmartStructure
    from canvas.span import SmartSpan

    all_poles = [
        i for i in scene_items
        if isinstance(i, (SmartPole, SmartStructure))
    ]
    existing_set = {p for p in all_poles if getattr(p, "is_existing", False)}

    while True:
        promoted = set()
        for pole in all_poles:
            if pole in existing_set:
                continue
            neighbours_existing = sum(
                1 for s in pole.connected_spans
                if (s.p1 if s.p2 == pole else s.p2) in existing_set
            )
            # Only relay SmartPoles can be promoted — SmartStructures
            # (DP, TP, 4P, DTR) are always new infrastructure and must
            # never be silently reclassified as existing.
            if neighbours_existing >= 2 and isinstance(pole, SmartPole):
                promoted.add(pole)
        if not promoted:
            break
        existing_set.update(promoted)

    for span in scene_items:
        if not isinstance(span, SmartSpan):
            continue
        override = getattr(span, "override_is_existing", "Auto")
        if override == "New":
            both_existing = False
        elif override == "Existing":
            both_existing = True
        else:
            both_existing = (
                span.p1 in existing_set and span.p2 in existing_set
            )
        new_val = both_existing and not span.is_service_drop
        if span.is_existing_span != new_val:
            span.is_existing_span = new_val
            if new_val:
                # Existing spans don't need CG by default
                span.has_cg = False
                if not span.is_lt_span and span.conductor == "ACSR":
                    span.wire_count = "3"
            span.update_visuals()


def auto_update_stays(scene_items: List[Any], angle_tolerance_deg: float = 20.0) -> None:
    """Auto-update stay counts and angles on poles based on span layout."""
    from canvas._base import SmartPole
    from canvas.span import SmartSpan

    for pole in scene_items:
        if not isinstance(pole, SmartPole):
            continue
        if pole.override_auto_stay:
            continue
        if pole.pole_type == "DTR":
            continue

        if pole.is_existing:
            existing_spans = [
                s for s in pole.connected_spans
                if not s.is_service_drop and s.is_existing_span
            ]
            new_spans = [
                s for s in pole.connected_spans
                if not s.is_service_drop and not s.is_existing_span
            ]

            should_stay = False
            if new_spans and existing_spans:
                tol = angle_tolerance_deg
                lo = 180.0 - tol
                hi = 180.0 + tol

                def _span_angle_deg(span: SmartSpan) -> float | None:
                    other = span.p1 if span.p2 == pole else span.p2
                    dx = other.x() - pole.x()
                    dy = other.y() - pole.y()
                    if math.hypot(dx, dy) <= 0:
                        return None
                    return math.degrees(math.atan2(dy, dx)) % 360.0

                ex_angles = [a for a in (_span_angle_deg(s) for s in existing_spans) if a is not None]
                new_angles = [a for a in (_span_angle_deg(s) for s in new_spans) if a is not None]

                for exa in ex_angles:
                    for nwa in new_angles:
                        pair_angle = (nwa - exa) % 360.0
                        if pair_angle < lo or pair_angle > hi:
                            should_stay = True
                            break
                    if should_stay:
                        break

            target = 1 if should_stay else 0
            needs_visual_refresh = (pole.stay_count != target)
            if needs_visual_refresh:
                pole.stay_count = target
            if pole.stay_angle_override is not None:
                pole.stay_angle_override = None
                needs_visual_refresh = True
            if needs_visual_refresh:
                pole.update_visuals()
            continue

        active_spans = [
            s for s in pole.connected_spans
            if not s.is_service_drop and not s.is_existing_span
        ]
        n = len(active_spans)
        should_stay = False

        if n == 1:
            should_stay = True
        elif n == 2:
            s1, s2 = active_spans
            other1 = s1.p1 if s1.p2 == pole else s1.p2
            other2 = s2.p1 if s2.p2 == pole else s2.p2
            v1 = (other1.x() - pole.x(), other1.y() - pole.y())
            v2 = (other2.x() - pole.x(), other2.y() - pole.y())
            mag1 = math.hypot(*v1)
            mag2 = math.hypot(*v2)
            if mag1 > 0 and mag2 > 0:
                dot = v1[0] * v2[0] + v1[1] * v2[1]
                angle = math.degrees(
                    math.acos(min(1.0, max(-1.0, dot / (mag1 * mag2))))
                )
                if (180 - angle) > 20:
                    should_stay = True

        target = 1 if should_stay else 0
        needs_visual_refresh = (pole.stay_count != target)
        if pole.stay_count != target:
            pole.stay_count = target
        if needs_visual_refresh:
            pole.update_visuals()

