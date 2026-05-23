# dPHM-PINN Model Architecture

## Components

- Differentiable physical hydraulic model (dPHM).
- Graph/temporal neural components for physics-informed prediction.
- Physics residual and calibration losses.
- Replay/calibration datasets aligned to canonical node/edge axes.

## Design rule

The model consumes normalized canonical network and telemetry structures. Vendor/protocol details remain outside the model core.
