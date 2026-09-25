"""canvas package — interactive drawing objects for ERP Estimate Generator."""
from canvas._base import _NodeMixin, SmartPole
from canvas.nodes import SmartStructure, SmartConsumer
from canvas.span import SmartSpan
from canvas.annotations import CanvasSymbol, CanvasTextBox, CanvasLegendItem
from canvas.grid import GridManager
from canvas.canvas_ops import (
    is_ht_node, get_node_voltage, active_connected_spans,
    span_other_endpoint, span_exists_between, has_path_between,
    validate_span_creation, find_nearby_node
)

__all__ = [
    'SmartPole', 'SmartStructure', 'SmartConsumer', 'SmartSpan',
    'CanvasSymbol', 'CanvasTextBox', 'CanvasLegendItem', 'GridManager',
    'is_ht_node', 'get_node_voltage', 'active_connected_spans',
    'span_other_endpoint', 'span_exists_between', 'has_path_between',
    'validate_span_creation', 'find_nearby_node'
]

