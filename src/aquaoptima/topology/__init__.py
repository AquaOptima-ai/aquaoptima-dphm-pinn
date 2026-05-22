"""Topology / graph-building utilities for the dPHM-PINN."""

from .graph_builder import (
    EDGE_FEATURE_DIM,
    NODE_FEATURE_DIM,
    GraphFeatures,
    build_graph_features,
)
from .masks import sensor_mask_from_indices, virtual_node_mask

__all__ = [
    "EDGE_FEATURE_DIM",
    "NODE_FEATURE_DIM",
    "GraphFeatures",
    "build_graph_features",
    "sensor_mask_from_indices",
    "virtual_node_mask",
]
