# AMAX-5580 Vendor PAC Software Inventory / Integration Boundary

Sprint 52 converts the AMAX-5580 user manual, AMAX-5000 I/O manual,
and AMAX5580 Linux driver package findings into an implementation-facing
AquaOptima boundary. This is not a replan-only sprint: it ships SDK
contracts, tests, and this manual-grounded inventory.

The non-negotiable safety boundary remains unchanged:

- no live OT binding
- no PLC/PAC/SCADA write
- no command emission
- no setpoint output
- no control-loop closure
- no direct VFD / pump / actuator control from AquaOptima Edge

## Source evidence

The Sprint 52 inventory references three vendor evidence sources:

1. `AMAX-5580_User_Manual_Ed.2-FINAL.pdf`
   - local extracted reference: `AMAX-5580_User_Manual_Ed.2-FINAL.txt`
   - SHA256: `88c1c1bf5bea54283190c284dcc7b32c68cb3d3a52bc19d1afe5e2c3d9f981de`
2. `AMAX-5000_User_Manual_Ed.5_FINAL.pdf`
   - local extracted reference: `AMAX-5000_User_Manual_Ed.5_FINAL.txt`
   - SHA256: `115fd1e2d3763b93b9c534a4452dceec034b41d36cc1ad36658fa70c3327b509`
3. `AMAX5580 Linux driver.zip`
   - package version observed: `v2.24-1`
   - SHA256: `a8d89973d97c3004f384be864cfc94582547fc588bf8c48fc6707db69341d220`

## AMAX-5580 product offering distinction

The AMAX-5580 manual distinguishes two product personalities.

### Control IPC Barebone

The Control IPC Barebone offering includes part numbers such as:

- `AMAX-5580-C3000A`
- `AMAX-5580-54000A`
- `AMAX-5580-74000A`

This path is closer to a configurable industrial control IPC. The
manual records CPU/RAM options including Celeron 3955U / 4 GB, Core
i5-6300U / 8 GB, and Core i7-6600U / 8 GB. It does not by itself imply
that the CODESYS runtime and licenses are bundled.

### CODESYS Ready PAC

The CODESYS Ready PAC offering includes part numbers such as:

- `AMAX-658-6CCW00A`
- `AMAX-658-65CW00A`
- `AMAX-658-67CW00A`

The manual-confirmed CODESYS Ready PAC table lists:

- `Windows 10 LTSC` 64-bit
- 128 GB M.2 storage
- 2 MB NVRAM
- `CODESYS V3 Pure Control with Visu(HMI)`

This is the clearest manual-grounded PAC path. It makes AMAX/CODESYS
the PAC/control/HMI substrate, not just a generic edge PC.

## AMAX/CODESYS as the PAC/control substrate

The AMAX-5580 manual says AMAX-5000 integrates with 3S CODESYS as an
IEC-61131-3 controller. With EtherCAT support in CODESYS, AMAX-5000 can
implement very fast control processes in the microsecond range, and can
support motion-control tasks potentially up to 256 axes depending on
cycle time.

Therefore, AquaOptima must not build a competing PAC runtime. The
correct split is:

- AMAX/CODESYS owns hard real-time control.
- AMAX/CODESYS owns EtherCAT field I/O.
- CODESYS Visu/HMI or site HMI owns operator visualization/authority.
- Site PLC / AMAX PAC owns interlocks, permissives, and actuator authority.
- AquaOptima owns model inference, validation, dry-run proposal records,
  advisory/evidence records, and read-only health/status evidence.

## AMAX-5000 EtherCAT slice I/O capability families

The AMAX-5000 I/O manual confirms these EtherCAT slice I/O families:

- Power / coupler / extension:
  - `AMAX-5001`
  - `AMAX-5074`
  - `AMAX-5079`
- Analog I/O:
  - `AMAX-5015`
  - `AMAX-5017C`
  - `AMAX-5017V`
  - `AMAX-5017VW`
  - `AMAX-5017H`
  - `AMAX-5018`
  - `AMAX-5024`
- Digital I/O:
  - `AMAX-5051`
  - `AMAX-5052`
  - `AMAX-5056`
  - `AMAX-5056SO`
  - `AMAX-5057`
  - `AMAX-5057SO`
- Relay:
  - `AMAX-5060`
- Counter / encoder:
  - `AMAX-5080`
  - `AMAX-5081`
  - `AMAX-5082`
- Timestamp I/O:
  - `AMAX-5051T`
  - `AMAX-5056T`

These are CODESYS/EtherCAT/PAC capabilities. AquaOptima should consume
validated evidence from this layer; it should not implement a Python
EtherCAT master or control loop.

## Linux driver package scope

The AMAX5580 Linux driver package is important but narrower than the
PAC software stack. It covers Advantech EC/platform capabilities such as:

- watchdog
- hardware monitor / `hwmon`
- LED
- GPIO
- EEPROM
- brightness/common EC support

The examples reference `/dev/watchdog`, `/dev/advgpio`, LED control,
EEPROM, and a watchdog daemon.

Important caveat:

> Linux driver package does not prove CODESYS Linux availability or
> licensing.

The Linux driver package confirms Linux EC/platform support. It does
not prove that the same CODESYS runtime, Visu/HMI, EtherCAT packages,
protocol packages, or licenses are available on Linux for the selected
AMAX-5580 SKU. Those remain vendor-confirmation questions.

## AquaOptima reuse-vs-build boundary

| Capability area | Owner | AquaOptima mode |
|---|---|---|
| hard real-time control | AMAX/CODESYS PAC | out of scope |
| EtherCAT field I/O | AMAX/CODESYS PAC | reuse / observe evidence |
| HMI / Visu | CODESYS Visu or site HMI | reuse |
| interlocks / permissives | site PLC or AMAX PAC | out of scope |
| actuator authority | site PLC or AMAX PAC | out of scope |
| model inference | AquaOptima sidecar | advisory |
| validation | AquaOptima sidecar | advisory |
| dry-run proposals | AquaOptima sidecar | dry-run evidence |
| advisory/evidence records | AquaOptima sidecar | advisory evidence |
| read-only health/status | AquaOptima sidecar | read-only observe |

## Explicit correction for future work

Future AMAX work must not assume AquaOptima is building the PAC. AMAX
and CODESYS already provide the PAC/control substrate for the
CODESYS Ready PAC model. Future work should integrate around this
substrate.

Do not implement by default:

- live OPC UA / Modbus / CODESYS / SCADA clients
- a CODESYS project generator
- a Python EtherCAT master
- direct field-I/O control
- direct actuator control
- write authorization
- setpoint output
- command emission
- control-loop closure

## Open vendor-confirmation questions

Before purchasing or piloting, confirm with Advantech:

1. Which exact AMAX-5580 SKU includes CODESYS runtime and Visu/HMI?
2. Which licenses are bundled and which are separate?
3. Are OPC UA, Modbus TCP/RTU, MQTT/Sparkplug, and fieldbus packages
   included or separately licensed?
4. Is CODESYS Linux Control officially supported on AMAX-5580?
5. If Linux is supported, is there a CODESYS Ready PAC Linux SKU, or is
   it an integrator-installed path?
6. Can Python 3.10+, ONNX Runtime, PyTorch CPU, or OpenVINO run safely
   as a sidecar beside CODESYS?
7. Is Docker/Podman or another container runtime supported on the
   official OS image?
8. How should CPU/RAM be reserved so CODESYS real-time tasks are not
   disturbed by AquaOptima sidecar inference?

Sprint 52 therefore grounds the next phase: AquaOptima should be a
sidecar advisory/evidence layer beside AMAX/CODESYS, not a competing
PAC runtime.

## Supplier update: AMAX-8580 replaces AMAX-5580

After Sprint 52 was prepared, the supplier advised that AMAX-5580 will
stop production and that the replacement platform is **AMAX-8580**. The
AMAX-8580 product is expected to release in approximately three months,
and detailed user-manual / ordering / licensing evidence is not yet
available beyond the current datasheet-level information.

This document therefore remains the final AMAX-5580 vendor inventory,
but it should now be read as **legacy fallback / historical evidence**.
The forward AquaOptima Edge target should move to AMAX-8580 once vendor
availability, exact SKU, OS image, CODESYS license/package, RAM/storage,
real-time BIOS, and MRAM/NVRAM details are confirmed.

The architecture boundary does not change:

- AMAX/CODESYS remains the PAC/control substrate;
- AquaOptima remains the sidecar advisory / inference / validation /
  dry-run proposal / evidence layer;
- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure.

Until AMAX-8580 details are confirmed, do not encode AMAX-8580 as a
qualified deployment target. Treat it as the intended successor target
with open vendor-confirmation gates.
