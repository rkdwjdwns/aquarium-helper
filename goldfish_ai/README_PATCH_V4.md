# Goldfish AI v4 Patch

## Scope

This patch aligns the Raspberry Pi runtime with the project's final presentation architecture:

- Sensor values: existing server API path
- TDS: ppm, not NTU
- AI presentation data: separate Activity / ABR / FRS / Growth CSVs
- Environment control: HEATER, COOLING, LIGHT
- AIR_PUMP: always on, not controlled
- FEEDER: external app device, not controlled
- AI direct control: ABR-based temporary LIGHT REST override

## AI control flow

```text
Camera
  -> YOLO11 / ByteTrack
  -> calibrated behavior features
  -> Activity / ABR v2
  -> AIControlPolicy
       NORMAL
       WATCH
       REST
  -> light_timer
  -> LIGHT
```

Default REST trigger:
- dashboard ready
- quality GOOD or FAIR
- ABR >= 13%
- normal light schedule currently ON
- condition observed twice consecutively

REST behavior:
- force LIGHT OFF for 20 minutes
- then release to the normal schedule
- block re-entry for 30 minutes

Configuration is under `ai_control.light_rest` in `config.yaml`.

## Presentation CSVs

Under `data/presentation/`:
- `activity_dashboard.csv`
- `abr_dashboard.csv`
- `feeding_response_v2.csv`
- `growth_dashboard.csv`

Additional runtime decision log:
- `ai_control_decisions.csv`

The decision log is not a fifth analysis model. It is the audit trail for the AI-to-hardware control decision.

## Hardware warning

The GitHub/recovered `command_poller.py` uses a simulation `set_relay()` by default. The v4 logic can decide and request LIGHT ON/OFF, but physical switching requires the Raspberry Pi's actual relay/GPIO implementation.

If the deployed Pi already has a real GPIO implementation, preserve that `set_relay()` function and merge only the v4 ownership changes around it.

## Current control ownership

- HEATER / COOLING: server command polling
- LIGHT: local `light_timer.py` + AI REST
- AIR_PUMP: always on
- FEEDER: external app
- FILTER: excluded

This ownership separation prevents the server poller from immediately turning LIGHT back on while AI REST is active.
