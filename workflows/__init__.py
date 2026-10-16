"""
workflows — a small dynamic, config-driven pipeline engine for the
Polish Funds Analyzer.

Compose analysis steps (screen, filter, portfolio, rebalance, alert,
project_fees, export) in a YAML/JSON spec and run them as a pipeline, with a
shared context passed between steps. See ``workflows/engine.py``.
"""

from .engine import (
    STEP_REGISTRY,
    WorkflowContext,
    register_step,
    run_workflow,
    load_and_run,
)

__all__ = [
    "STEP_REGISTRY",
    "WorkflowContext",
    "register_step",
    "run_workflow",
    "load_and_run",
]
