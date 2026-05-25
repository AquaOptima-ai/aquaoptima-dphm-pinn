# AMAX-5580 Feasibility Evidence / SKU & OS Decision Gate

Sprint 46 deliverable. Turns Advantech AMAX-5580 datasheet facts and
the Sprint 45 SDK assumptions into a concrete feasibility note so the
product owner can pin a SKU / OS / runtime path before deeper Edge
implementation begins. This is an evidence and decision-gate document,
not an Edge Runtime implementation specification.

The non-negotiable safety boundary is reaffirmed throughout:

- no live OT binding
- no PLC/PAC/SCADA write
- no command emission
- no setpoint output
- no control-loop closure
- the site PLC / pump-station PLC retains direct VFD / pump /
  actuator authority

## 1. Executive decision summary

**Recommended primary target profile:**
`advantech-amax-5580-i5-or-i7-8gb-linux-codesys-cpu-first` — an AMAX-5580
fitted with either a Core i5-6300U (2.4 GHz dual core, 8 GB RAM) or a
Core i7-6600U (2.6 GHz dual core, 8 GB RAM), running AdvLinuxTU v2.0.5.4
(Ubuntu 18 based) with CODESYS Linux Control V3 SP20 and a direct
PyTorch CPU install for the AquaOptima Edge inference path.

**Go / no-go language.** Proceed with caution. The AMAX-5580 is a
credible PAC-class x86_64 industrial controller and the i5/i7 8 GB SKUs
plausibly accommodate dPHM-PINN CPU inference, but every claim in this
document is **surrogate evidence** until real AMAX-5580 hardware is in
hand and benchmarked. Recommendation: approve this profile as the
Sprint 47 benchmarking target subject to the evidence gaps listed in
§7, and treat any unexpected packaging or runtime constraint surfaced
in Sprint 47 as a stop condition that re-opens the decision gate.

**What is still surrogate.** Until real AMAX hardware testing in
Sprint 47:

- Python `>= 3.10` wheel availability on Ubuntu 18 based AdvLinuxTU is
  inferred from Ubuntu 18 packaging norms; not yet verified on a real
  AdvLinuxTU image.
- Modern PyTorch CPU wheel glibc requirements vs the AdvLinuxTU glibc
  are inferred; not yet verified.
- CPU inference latency / memory envelope / thread policy for the
  dPHM-PINN model on i5-6300U / i7-6600U at 8 GB is unmeasured.
- CODESYS Linux Control V3 SP20 co-tenancy with a long-running Python
  / PyTorch process on the same AMAX node is unobserved.
- Site-specific OT integration posture (OPC UA Server vs Modbus TCP vs
  CODESYS PLC Handler / shared memory) is open and depends on the
  customer engagement.

## 2. AMAX-5580 SKU comparison

The AMAX-5580 is an Intel Core / Celeron based embedded controller /
IoT control platform from Advantech, marketed as a PAC-class industrial
controller. The datasheet enumerates three CPU + RAM SKUs in scope.

| SKU id (SDK)                                  | CPU                              | Cores  | Clock   | RAM    | Tier                       | Notes                                                                 |
|-----------------------------------------------|----------------------------------|--------|---------|--------|----------------------------|-----------------------------------------------------------------------|
| `advantech_amax_5580_celeron_3955u_4gb`       | Intel Celeron 3955U              | 2      | 2.0 GHz | 4 GB   | `constrained_fallback`     | Constrained fallback only. 4 GB RAM leaves marginal headroom for PyTorch CPU; not the primary target. |
| `advantech_amax_5580_core_i5_6300u_8gb`       | Intel Core i5-6300U              | 2      | 2.4 GHz | 8 GB   | `serious_candidate`        | Serious candidate. 8 GB RAM gives the dPHM-PINN process meaningful headroom. |
| `advantech_amax_5580_core_i7_6600u_8gb`       | Intel Core i7-6600U              | 2      | 2.6 GHz | 8 GB   | `recommended_candidate`    | Recommended candidate for Sprint 47 CPU inference benchmarking; highest clock among the in-scope SKUs. |

**Recommendation.** Use either the i5-6300U / 8 GB or i7-6600U / 8 GB
SKU as the Sprint 47 benchmarking target. Treat Celeron 3955U / 4 GB as
a constrained fallback only — keep the SKU profile in the SDK evidence
record but do not size the dPHM-PINN deployment plan against it.

## 3. OS / CODESYS decision matrix

| OS                                            | CODESYS runtime                 | Python / ML packaging risk | Site fit                                          | Recommendation                                 |
|-----------------------------------------------|---------------------------------|----------------------------|---------------------------------------------------|------------------------------------------------|
| AdvLinuxTU v2.0.5.4 64-bit (Ubuntu 18 base)   | CODESYS Linux Control V3 SP20   | Moderate                   | Strong when CODESYS Linux is acceptable on-site   | Primary target for Sprint 47 benchmarking      |
| Windows 10 LTSC 2019 64-bit                   | CODESYS Control RTE V3.5 SP20   | Moderate                   | Strong when CODESYS Windows is already standard   | Viable fallback when site requires Windows     |

**Why Ubuntu 18 / AdvLinuxTU is the moderate-risk path.** Python
`>= 3.10` is required by the dPHM-PINN stack and the Sprint 45 SDK
profile. Ubuntu 18 ships with Python 3.6 by default. Reaching Python
3.10+ on AdvLinuxTU likely requires either pyenv, a vendored
interpreter, deadsnakes-style backports, or building from source.
Modern PyTorch CPU wheels (manylinux2014 and newer) target a glibc
version that AdvLinuxTU may or may not satisfy depending on the image
revision. None of this is fatal — but every assumption needs to be
verified on real hardware. The container sidecar option (see §4)
sidesteps both risks at the cost of operational complexity.

**Why Windows + CODESYS RTE is also moderate-risk.** CODESYS Control
RTE V3.5 SP20 on Windows 10 LTSC 2019 is well-trodden and may be the
right answer for a customer site that has already standardised on
CODESYS for Windows. The cost is on the Python / PyTorch side: ML
packaging on Windows is less mature than on Linux, vendor wheels are
sometimes lagged, and PyTorch CPU build matrices are smaller. The path
is viable but expect more friction during the Sprint 47 packaging
smoke harness.

**1 ms real-time control claim.** Advantech states an optimised
BIOS / embedded OS for 1 ms real-time control on both Windows and
Linux. That is a CODESYS-side claim, not an AquaOptima Edge claim:
AquaOptima Edge remains **supervisory / audit only**. No part of the
AquaOptima stack participates in the real-time control loop, and there
is **no live OT binding**, **no PLC/PAC/SCADA write**, **no command
emission**, and **no setpoint output** from the AquaOptima inference
path. The site PLC retains direct VFD / pump / actuator authority.

## 4. Runtime / package strategy decision matrix

The choice is how to ship the AquaOptima dPHM-PINN model alongside the
CODESYS runtime on the AMAX node. Five candidates considered.

| Option                                         | Pros                                                                                 | Cons                                                                              | Verdict                                                                 |
|------------------------------------------------|--------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| Direct Python + PyTorch CPU install            | Simplest, fewest moving parts, easiest debugging, easiest CI parity                  | Depends on AdvLinuxTU Python `>= 3.10` and glibc; may need pyenv or vendored runtime | **Recommended baseline** for Sprint 47 benchmarking on i5/i7 8 GB        |
| Containerised sidecar (Docker / Podman)        | Decouples Python / glibc / PyTorch from host OS image; reproducible packaging         | Adds container infrastructure to OT site; image distribution overhead             | **Recommended low-risk fallback** when direct install is blocked         |
| Service / sidecar outside CODESYS runtime      | Removes any co-tenancy concern with CODESYS; clearer process boundary                | Still requires a Python runtime on the host                                       | Useful framing once Sprint 47 measures co-tenancy behavior               |
| ONNX Runtime CPU                               | Smaller dependency footprint than PyTorch; mature Windows + Linux support             | Requires ONNX export of the dPHM-PINN model and parity testing                    | Queue for Sprint 47 follow-up benchmarking, not the baseline             |
| OpenVINO                                       | Intel-specific CPU optimisations on the AMAX-5580 Intel parts                         | Adds OpenVINO toolchain and model conversion path                                 | Queue for Sprint 47 follow-up benchmarking, not the baseline             |

**Sprint 47 benchmarking path recommendation.** Start with direct
PyTorch CPU install on the recommended SKU. Once latency / memory /
thread baselines are established, run the same benchmarks under ONNX
Runtime CPU and OpenVINO to quantify the gain (if any) from the
alternative runtimes. Container sidecar is the packaging fallback —
keep it warm but only adopt it if direct install hits an unrecoverable
AdvLinuxTU / glibc / Python wheel obstacle.

## 5. CODESYS / PLC integration option matrix

The AMAX-5580 datasheet enumerates OT and IT protocol packages
available through CODESYS bundles. AquaOptima Edge uses **only the
read-only / audit-only** subset of these. The control authority stays
with the site PLC / pump-station PLC.

| Integration                                                              | Use as                                  | AquaOptima access mode | Notes                                                                                       |
|--------------------------------------------------------------------------|-----------------------------------------|------------------------|---------------------------------------------------------------------------------------------|
| OPC UA Server (CODESYS package)                                          | Telemetry read                          | Read-only / audit-only | Likely Sprint 48+ adapter; no write authority from AquaOptima                                |
| Modbus TCP Client / Server (CODESYS package)                             | Telemetry read                          | Read-only / audit-only | Common LV/MV pump-station integration; AquaOptima never opens a write coil                   |
| Modbus RTU Client                                                        | Telemetry read                          | Read-only / audit-only | Useful for serial-only legacy devices behind RS-485                                          |
| CODESYS PLC Handler / shared memory                                      | Telemetry read                          | Read-only / audit-only | Available where CODESYS exposes a co-located handler; never a control authority for AquaOptima |
| EtherCAT MainDevice / PROFINET IO-Controller / EtherNet/IP Scanner       | OT field bus                            | Out of scope            | CODESYS / site PLC concern only; AquaOptima does not participate                              |
| PROFIBUS Master / CANopen Manager                                        | OT field bus                            | Out of scope            | Same as above                                                                                |
| MQTT / Sparkplug                                                         | IT / integration only                   | Read-only / audit-only | Useful for cloud / Operations Console hand-off; **not** a control authority                  |
| ODBC (Advantech CODESYS package)                                         | IT integration                          | Read-only / audit-only | Historian / reporting only; not a control path                                               |

**Boundary reminder.** These remain read-only or audit-only. Until a
future explicit safety gate, no integration in the table above carries
control authority for AquaOptima:

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no direct VFD / pump / actuator control from AquaOptima Edge;
- no bypass of site PLC interlocks, permissives, trips, manual mode,
  or emergency stop.

## 6. OT hardware facts to carry forward

These AMAX-5580 datasheet facts apply across every SKU and OS choice
above. Document them once here; downstream Sprint 47+ planning should
treat them as the canonical OT-hardware envelope.

- **Networking and I/O.** 2 x GbE LAN, 4 x USB 3.0, 2 x RS-232 / 422 /
  485 (serial), HDMI / VGA display.
- **Power.** Dual 24 VDC input with alarm output. 24 VDC ±20%.
- **Expansion.** AMAX-5000 EtherCAT Slice I/O for distributed field
  I/O; AMAX-5400 PCIe expansion for additional cards.
- **Retain / persistence memory.** Optional retain / persistence
  memory for CODESYS runtime state.
- **Environment.** Operating temperature -10 °C to 60 °C.
- **Certifications and shock / vibration.** CE, FCC, CB / UL62368,
  plus the shock and vibration ratings noted on the Advantech
  datasheet.

These facts shape installation, environmental, and panel-design
decisions; they do **not** change the AquaOptima Edge boundary. The
AquaOptima inference path remains audit-only regardless of how the
AMAX-5580 is wired into the OT panel.

## 7. Recommendation / acceptance gate

**Recommended target profile.**
`advantech-amax-5580-i5-or-i7-8gb-linux-codesys-cpu-first`, unless the
customer site explicitly requires Windows CODESYS — in which case
fall back to the Windows 10 LTSC 2019 + CODESYS Control RTE V3.5 SP20
variant.

**What must be approved before Sprint 47:**

1. SKU tier — confirm i5-6300U / 8 GB or i7-6600U / 8 GB is acceptable
   (the SDK records both as serious / recommended candidates).
2. OS path — confirm AdvLinuxTU + CODESYS Linux Control V3 SP20 as
   primary, with Windows 10 LTSC 2019 + CODESYS RTE V3.5 SP20 only as
   a site-required fallback.
3. Packaging strategy — confirm direct PyTorch CPU install as the
   Sprint 47 baseline, with container sidecar as the documented
   fallback when direct install is blocked.
4. ML runtime sequence — confirm PyTorch CPU first, ONNX Runtime CPU
   and OpenVINO as follow-up benchmarking only.
5. Surrogate evidence acceptance — confirm that all claims in this
   document are surrogate until real AMAX hardware is in hand and
   that Sprint 47 may surface a stop condition.

**Sprint 47 scope (after this gate is accepted).** Sprint 47 should
be a CPU inference benchmark / packaging smoke harness only —
specifically: measure dPHM-PINN CPU inference latency, memory
envelope, and thread policy on a real AMAX-5580 (or representative
i5-6300U / i7-6600U / 8 GB surrogate); verify Python `>= 3.10` and
PyTorch CPU wheel installation on the chosen OS path; produce
packaging evidence the SDK can consume. Sprint 47 must **not**
introduce live OT binding, PLC/PAC/SCADA write, command emission,
setpoint output, control-loop closure, or any Edge Runtime daemon
implementation.
