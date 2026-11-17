# SPAM 2D Scan

Open **Experiments → Daily characterization → EA / EC → SPAM 2D Scan**.
Choose the FPGA and each axis's family, device, channel, parameter, start/end,
point count and settle delay. X varies fastest; both axes scan in ascending
order with endpoints included. Each cell runs both states and all repeats of
the unchanged SPAM PulseRunner, through a separate instance that preserves the
standalone SPAM tab's results. Save/load uses separate `spam_2d` presets.

| Target | Axes | Units |
| --- | --- | --- |
| Windfreak A/B | Power, frequency | dBm, MHz |
| SG384 N/BNC | Power, shared frequency | dBm, MHz |
| AnaPico | Frequency | MHz |
| DDS channels 1–4 | VVA level, frequency | integer 0–1000, MHz |
| SPAM | Detection, initialization, cooling, π pulse, AOM wait | µs |

DDS VVA is a control setting, not calibrated optical power. Frequency converts
to Hz and SPAM time to 10 ns ticks. Axis spacing must match that parameter's
resolution; duplicate physical axes and grids above 10,000 cells are rejected.
RF power limits and parameter ranges are checked before starting. Existing
device APIs retain their ramp/readback validation. Configure output ON/OFF and
references in the equipment controls. Threshold stays fixed throughout a scan.

The default restore option reads both starting device-axis values before any
write and restores them after success, failure or Stop. Unknown initial values
fail before writes. DDS readbacks may be last-transmitted settings. Restoration
failures are recorded. Turning restore off leaves the last requested settings.
The local client reserves the FPGA and rejects other control requests to the
axis device workers during the scan; other clients on the server are not locked.

Select average error, fidelity, state-specific error or acceptance in the map.
Gray cells have no completed/valid result; crosses mark failed/cancelled points.
Click a cell to inspect both histograms and accepted/attempted/received counts.
Fidelity uses the existing conditional, equally weighted state definition.

Automatic output: `configuration.json`, FPGA mapping, `initial_values.json`,
`points.json`, `result.json`, `summary.csv`, `heatmap.png`, and per-point folders
containing the existing raw FIFO, counts, configuration and analysis files.
CSV metrics are fractions (0–1); the UI shows percentages. Relative point paths
allow moving the entire run folder. Default location is
`labremote/data/characterization/<EA|EC>/spam_2d/<date>/<FPGA alias>/`.

Stop retains partial data, waits for FPGA cleanup and attempts restoration.
Open a run's `result.json` to revisit it. Image export saves the displayed metric.
The shared Queue button freezes the scan settings and FPGA mapping for later use.

Automated validation uses fake devices. Real hardware timing, routing and settle
delays still need laboratory verification.
