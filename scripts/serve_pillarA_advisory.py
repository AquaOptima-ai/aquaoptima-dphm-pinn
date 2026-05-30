#!/usr/bin/env python3
"""AOPSO Sprint 36 -- thin CLI shim for the Pillar-A advisory container.

This is the file the Dockerfile sets as the ENTRYPOINT. It does nothing
clever: it just forwards argv into :func:`run_cli` from
``aquaoptima.advisory.packaging.serve_advisory``. The container is
designed to run with ``--read-only --network=none --user 1001:1001``,
and this shim respects that — it never opens a socket, never touches a
PLC / PAC / SCADA endpoint, never emits a setpoint, dispatch, or
actuation payload.
"""

from __future__ import annotations

import sys

from aquaoptima.advisory.packaging.serve_advisory import run_cli


if __name__ == "__main__":
    raise SystemExit(run_cli(sys.argv[1:]))
