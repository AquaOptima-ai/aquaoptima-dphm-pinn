# AOPSO Sprint 36 -- Pillar A Linux deployment image
#
# Builds a read-only, offline, advisory-only inference sidecar that runs the
# Sprint-35 ONNX health detector on an AMAX-5580 (linux/amd64 CPU) target.
#
# Boundary -- non-negotiable
#   * The image carries the .onnx + sidecar + a stdlib + onnxruntime CPU runtime.
#     It does NOT carry torch, the edge SDK, or any write-capable connector.
#   * Designed to run with: --read-only --network=none --user 1001:1001
#     The runtime entrypoint never opens a socket, never touches PLC / PAC /
#     SCADA, and never emits a setpoint or dispatch payload.
#   * The site PLC retains direct VFD / pump / actuator authority. This
#     sidecar is shadow / offline use only.

# ----- builder stage: vendor pinned wheels for fully-offline rebuilds ----- #
FROM --platform=linux/amd64 python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Vendor the small runtime stack the entrypoint actually needs. CPU-only by
# design: no torch, no CUDA, no GPU wheels.
COPY deploy/pillarA_advisory/requirements.txt /build/requirements.txt
RUN python -m pip install --no-cache-dir -r /build/requirements.txt

# ----- runtime stage: minimal, non-root, read-only-friendly ----- #
FROM --platform=linux/amd64 python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Pull the site-packages from the builder. Keeps the final image small and
# avoids running pip in the runtime layer.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Non-root user. The image is designed to run with --user 1001:1001.
RUN groupadd --system --gid 1001 aopso \
 && useradd  --system --uid 1001 --gid aopso --no-create-home aopso

WORKDIR /app

# Copy the advisory runtime code, the ONNX artifact, and the sidecar. The
# /app tree is the only thing the entrypoint reads from; it is intended to
# be mounted read-only at runtime.
COPY src/aquaoptima/advisory/packaging /app/aquaoptima/advisory/packaging
COPY src/aquaoptima/advisory/__init__.py /app/aquaoptima/advisory/__init__.py
COPY src/aquaoptima/__init__.py /app/aquaoptima/__init__.py
COPY data/eval/packaging/pillarA_health_detector.onnx /app/model/pillarA_health_detector.onnx
COPY data/eval/packaging/pillarA_health_detector.sidecar.json /app/model/pillarA_health_detector.sidecar.json
COPY scripts/serve_pillarA_advisory.py /app/serve_pillarA_advisory.py

ENV PYTHONPATH=/app

# Volume mount points the caller is expected to bind in read-only / writable
# at run time:
#   /telemetry  -> read-only input (CSV / JSON records)
#   /evidence   -> writable evidence sink (the ONLY writable mount)
VOLUME ["/telemetry", "/evidence"]

USER 1001:1001

ENTRYPOINT ["python", "/app/serve_pillarA_advisory.py"]
CMD [ \
    "--onnx",         "/app/model/pillarA_health_detector.onnx", \
    "--sidecar",      "/app/model/pillarA_health_detector.sidecar.json", \
    "--input",        "/telemetry/input.csv", \
    "--evidence-dir", "/evidence" \
]
