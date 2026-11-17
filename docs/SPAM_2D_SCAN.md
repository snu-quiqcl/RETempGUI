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

DDS VVA is a control setting, not calibrated optical power. All axes round to
the nearest supported step, with exact half steps away from zero. Each axis
editor displays its resolution and the full scrollable list of planned values
before Run. Duplicate rounded values or duplicate serialized commands are
rejected, along with the existing range/count checks.

| Axis | Scan resolution / command grid | Basis |
| --- | --- | --- |
| Windfreak power | 0.01 dBm | SynthHD power specification (driver can encode 0.001 dBm) |
| Windfreak frequency | 0.1 Hz | local SynthHD driver sends MHz with 7 decimal places |
| SG384 N power | 0.01 dBm | SG380 manual, type-N power resolution |
| SG384 BNC power | 0.0001 dBm **command** grid | local SG384Safe formatting; physical BNC amplitude resolution is <1%, not a fixed dBm step; readback decides the final coordinate |
| SG384 frequency | 1 µHz | local SG384Safe sends Hz with 6 decimals; SG380 manual |
| AnaPico APSYN420 frequency | 0.001 Hz | local APSYN420 driver sends Hz with 3 decimals |
| DDS frequency | system_clock_hz / 2^48 | shipped DDSVVA 48-bit tuning-word conversion |
| DDS VVA | 1 | integer server parameter |
| SPAM times | 0.01 µs (10 ns) | existing FPGA sequence clock |

DDS frequency exposes **DDS system clock** (default 1000 MHz, the shipped
server default). It must match the server's configured clock; the current
status RPC does not expose that clock automatically. The client chooses the
nearest legal tuning word, then sends an interior-bin command to accommodate
the server's truncating FTW conversion. Preview shows the word-derived value,
not that tiny command offset. Commands are checked against parameter limits.

Both device axes are read after both writes and settle delays. A missing,
out-of-tolerance, duplicate, reversed, or inconsistent repeated-index readback
stops the scan before acquiring the affected cell. The final heatmap uses
completed cells' returned settings and midpoint cell boundaries. Unmeasured
coordinates retain the frozen plan unless a readback offset overlaps them;
then only those gray cells are interpolated/extrapolated between confirmed
coordinates to keep the live grid ordered. A run's saved axes are reused on reopen,
so later changes to rounding rules do not reinterpret old data. These are
setting readbacks, **not measurements of physical RF/optical power**; DDS values
are specifically marked `last_transmitted`. FPGA time axes are `fpga_ticks`.
Duplicate physical axes and grids above 10,000 cells are rejected.
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
`configuration.json` includes the planned `axis_values`, detailed `axis_plan`
(requested/applied/native command/tick), resolution descriptions and
`actual_axis_values` (null until confirmed). Point JSON/CSV `x`/`y` coordinates
are the returned applied settings, with separate `requested_x/y`, `planned_x/y`,
`command_x/y`, `readback_x/y`, and `x_source/y_source` columns. Commands use native
API units (Hz, dBm, integer VVA, FPGA ticks); other coordinates use display units.
Unconfirmed device coordinates are null. Failed cells remain visibly failed.
CSV metrics are fractions (0–1); the UI shows percentages. Relative point paths
allow moving the entire run folder. Default location is
`labremote/data/characterization/<EA|EC>/spam_2d/<date>/<FPGA alias>/`.

Stop retains partial data, waits for FPGA cleanup and attempts restoration.
Open a run's `result.json` to revisit it. Image export saves the displayed metric.
The shared Queue button freezes the scan settings and FPGA mapping for later use.

Automated validation uses fake devices. Real hardware timing, routing and settle
delays still need laboratory verification.

Resolution evidence reviewed for this implementation:

- [SRS SG380 manual](https://www.thinksrs.com/downloads/pdfs/manuals/SG380m.pdf), frequency resolution, type-N power and BNC amplitude specifications.
- [Windfreak SynthHD specifications](https://windfreaktech.com/product/microwave-signal-generator-synthhd/), power resolution. Frequency command precision is additionally limited by the local driver.
- Local `LabRemote_Client_UI_v4/server_deploy_latest/{SynthHD/SynthHD.py,SG380/SG384Safe.py,APSYN420/APSYN420.py}` for command formats. These are the available local server-driver copies, not an assertion that a remote server was inspected.
- This project's `server_deploy_latest/dds_vva.py` and `AD9912.py` for DDS clock, FTW conversion, and last-transmitted semantics; `labremote/characterization/spam_sequence.py` for time ticks.
