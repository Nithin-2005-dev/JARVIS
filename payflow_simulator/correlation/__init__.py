"""Explainable event relationships and incident grouping."""

from .config import CorrelationConfig, correlation_config_from_dict
from .engine import CorrelationEngine
from .storage import SQLiteCorrelationStore

__all__ = ["CorrelationConfig", "CorrelationEngine", "SQLiteCorrelationStore", "correlation_config_from_dict"]
