# Two-RF Micromotion Compensation

Open **Micromotion → Two-RF Compensation**. This page uses the same
`FPGAAPI.run_two_rf_compensation()` runner as the queue workflow
`labremote/workflow/two_rf_compensation.py`.

Choose the compensation DAC, common TRG/PMT signal names, voltage rectangle,
correlation acquisition settings, trap RF SG384 and output port (N/BNC).
The chamber presets are **EA: Low 0.16 / High 0.9 Vpp** and
**EC: Low 0.1 / High 0.19 Vpp**. Changing the chamber loads these values.
Select the SG384 and port actually wired to that chamber; neither is inferred.
By default, final verification uses the RF amplitude captured at run start.
Uncheck the restore-initial option to enter a custom final Vpp amplitude.

All RF inputs are Vpp. The existing SG384 API converts using its 50-ohm
convention and ramps through the existing configured voltage steps and interval.
Registry limits and device-specific caps are checked before changing hardware.
Unknown initial RF settings are rejected because restoration would be impossible.
This operation does not enable outputs or change RF frequency.

## Modes

* **Measurement/analysis:** snapshot RF and DAC; High RF settle/scan/fit;
  Low RF settle/scan/fit; intersection analysis; restore initial RF and DAC.
* **Apply/verify:** perform the same scans, set final operating RF, apply the
  intersection, then acquire a fresh correlation histogram. Retain RF/DAC only
  if `visibility + 1.96 * visibility_se <= max_visibility`. Failure or Stop
  before the verified commit restores the initial settings. Stop after the
  completed commit does not undo a successful compensation.

The DAC shared-control lease stays held and renewed across both conditions.
Only L_IN/R_IN are written. Their initial values are restored between scans.
Cleanup uses an independent cancellation group; failed RF restoration does not
prevent the DAC restoration attempt. Unconfirmed cleanup fails the job and stops
queue continuation. Physical DAC voltage readback is unavailable; the snapshot
is the server's last-requested state. The DAC lease is also renewed during SG384
ramps, including restoration ramps.

## Acceptance and results

Each valley must pass the existing fitting quality gate. Nearly parallel lines,
an intersection outside the common scan rectangle, excessive uncertainty, or a
95% marginal interval extending beyond that rectangle are rejected. Uncertainty
propagates both fit covariance matrices assuming independent scans and the local
rank-one model; calibration errors and inter-scan drift are not included.

The UI displays both visibility maps and the overlaid valley intersection with
error bars. Save/load settings and open archived results are supported. Loaded
results are view-only; applying requires a fresh complete run.

Each run has `results.json`, `high/` and `low/` raw FIFO/point/partial files and
scan results, plus verification FIFO and partial data in apply mode. A failed or
cancelled run retains completed points and its failure/cleanup status.

## Experiment Queue

Use the existing experiment-to-Queue action with **Two-RF Compensation** active.
The job freezes page settings, device names and FPGA profile. Both modes call
the same runner as the UI. Alternatively enqueue `two_rf_compensation.py` with
`parameters = {"fpga": "...", "dac": "...", "settings": {...}}`.

Tests use mock devices. Real trap RF wiring, calibrated High/Low values, settling
time and the laboratory's verification threshold must be checked on hardware.
