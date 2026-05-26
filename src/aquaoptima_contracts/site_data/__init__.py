"""Sprint 53 — Site Data Validation / dPHM Readiness contracts.

Sprint 53 starts the hardware-independent Site Data Validation /
dPHM Readiness phase. AMAX-specific work is paused until AMAX-8580
documentation and vendor details mature; this module lets AquaOptima
ask a customer for a minimum viable pump-system dataset and grade
whether the dataset is good, usable, poor, or blocked for testing
dPHM / dPL / dPHM-PINN without AMAX and without live OT integration.

Boundary (reaffirmed):

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no live OPC UA / Modbus / CODESYS / SCADA / PLC / MQTT / HTTP /
  database / message-broker client;
- no Edge Runtime daemon / service implementation;
- no AMAX hardware probing;
- no credentials, passwords, tokens, API keys, license keys, or
  connection secrets in docs / tests / source.
"""

from .intake import (
    DPHM_READINESS_GRADE_BLOCKED,
    DPHM_READINESS_GRADE_GOOD,
    DPHM_READINESS_GRADE_POOR,
    DPHM_READINESS_GRADE_TOKENS,
    DPHM_READINESS_GRADE_USABLE,
    PUMP_SITE_CANONICAL_ROLES,
    PUMP_SITE_HYDRAULIC_ROLES,
    PUMP_SITE_PUMP_SPEED_ROLES,
    PUMP_SITE_PUMP_STATE_ROLES,
    SiteDataExportSchema,
    SiteDataFieldRequirement,
    SiteDataQualityRule,
    SiteDataReadinessAssessment,
    SiteTagMapTemplate,
    assess_site_data_readiness,
    default_pump_site_data_export_schema,
    default_site_data_quality_rules,
    default_site_tag_map_template,
)

__all__ = [
    "DPHM_READINESS_GRADE_BLOCKED",
    "DPHM_READINESS_GRADE_GOOD",
    "DPHM_READINESS_GRADE_POOR",
    "DPHM_READINESS_GRADE_TOKENS",
    "DPHM_READINESS_GRADE_USABLE",
    "PUMP_SITE_CANONICAL_ROLES",
    "PUMP_SITE_HYDRAULIC_ROLES",
    "PUMP_SITE_PUMP_SPEED_ROLES",
    "PUMP_SITE_PUMP_STATE_ROLES",
    "SiteDataExportSchema",
    "SiteDataFieldRequirement",
    "SiteDataQualityRule",
    "SiteDataReadinessAssessment",
    "SiteTagMapTemplate",
    "assess_site_data_readiness",
    "default_pump_site_data_export_schema",
    "default_site_data_quality_rules",
    "default_site_tag_map_template",
]
