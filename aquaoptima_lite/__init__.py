"""AquaOptima Pump Station Optimizer Lite.

Quick-win product package for a single legacy pump station.  This sprint
establishes the runtime contracts, configuration model, station snapshot,
and control-authority gate vocabulary.  No live PLC/PAC writes or network
clients are implemented here; the goal is to make control authority
explicit, configurable, audited, and gated so that no learner / AI /
Operations Console component can bypass PLC/PAC interlocks, manual mode,
trips, or this gate.
"""

__version__ = "0.1.0"
