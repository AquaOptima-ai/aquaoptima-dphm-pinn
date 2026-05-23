# System Overview

## Layers

1. Network import and diagnostics.
2. dPHM physics core.
3. dPHM-PINN model layer.
4. Telemetry tag mapping.
5. Shadow replay and calibration.
6. Advisory safety contract.
7. Runtime/deployment layer.
8. Future supervised-control/PAC edge layer.

## Data flow

EPANET/WNTR topology and offline telemetry are transformed into canonical dPHM network, diagnostics, tag maps, replay frames, and calibration/evaluation reports. Control outputs are explicitly out of scope until later safety-gated phases.
