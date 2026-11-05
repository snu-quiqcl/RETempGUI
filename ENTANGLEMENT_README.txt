Remote entanglement tab

Open an FPGA device in RETempGUI: Entanglement appears next to HOM.
Run Entanglement starts immediately. Add to Queue freezes the current settings.
An external workflow must configure the microwave generator first; this tab
never sends generator frequency/output commands. Detuning is used for FPGA timing.

Basis: zz skips MW; mw_detuned applies the resonant-calibrated half-pi durations
before the flip mirror settling wait. UI inputs are full pi times; half lengths
are computed automatically. Defaults: EA 81.10 us / EC 70.58 us (pi), -2000 Hz,
175 deg start-phase magnitude, 600 ms mirror settling, 100 us simultaneous
PMTFA/PMTFC readout. Bright iff counts > separately editable EA/EC threshold.
Relative phase change uses only the half-pi pulse START gap: EC start - EA start.
Detuning = f_MW - f_qubit; phase change = 360 * detuning_hz * start_gap_us * 1e-6.
The input remains an unsigned phase magnitude. The displayed signed phase uses
the actual FPGA gap, truncated to 10 ns ticks. Default: 243.05 us, -174.996 deg.
Assumes equal detunings and stable coherent relative MW phase; excludes path
offset and finite-pulse measurement-axis correction. No center-based phase.
Save settings writes settings plus versioned phase definition/calculation;
legacy flat settings still load. results.json configuration includes the same
phase metadata for standalone and Queue runs. Historical results are unchanged.

One FPGA execution is a batch. It terminates after one accepted herald/readout,
or exhaustion of groups x inner trials x FPGA loops. SYNC is not checked.
The six state words are EA counts, EC counts, group index, FPGA loop index,
herald flag, inner-trial index. All indices are zero-based. FIFO protocol v2:
162 rows tagged 100 (480 histogram words + six state words), then one row
[histogram_overflow, 2, 0, 101]. Histogram overflow rejects the batch.

Stop requests cancellation through the shared standalone/Queue execution path.
A batch interrupted before validated completion is marked aborted and excluded
from statistics. Successful/exhausted completed batches both contribute attempts.
Cleanup stops the FPGA and disables counters, then sets:
CCD_EC=1, CCD_EA=0; MW_A=MW_C=0; AOMA=AOMC=AOMB=AOMM=1;
EOM_7GA1=EOM_7GA2=EOM_7GC1=EOM_7GC2=1; EOM_2GA=EOM_2GC=0; TRIG=0.
This is a software stop, subject to serial response latency. Cleanup errors are
reported and block automatic Queue continuation. Mirror settling is not awaited
by cleanup; a new measurement batch applies its full collection-path wait.

Default data: labremote/data/entanglement/YYYY-MM-DD/<run>/
- results.json: configuration, hardware mapping, phase calculation, source hashes,
  run status, each batch's start/end/upload/FIFO times, communication durations,
  histograms, fits, exact attempt indices, detector counts and classified state,
  plus final accumulated histograms, probabilities and decay fits.
- raw_fifo.csv: every received FIFO row, including malformed/incomplete data.
- entanglement.png: final accumulated/latest plots and attempt/state statistics.
- source/: exact Python and vendor definition snapshots for the run.

Geometric plot uses log-spaced ATTEMPT bins; the ordinate is bin probability.
Unsuccessful exhausted batches are right-censored and contribute attempted trials.
PC batch duration includes mirror settling, readout and communication; it is
not an FPGA herald timestamp. Count rate is based on the completed batch wall time.
Settings are saved independently with Save settings / Save settings as.
Vendor pin mappings are defined in labremote/devices/fpga/vendor/; restart after edits.

Validated offline using simulated FPGA control flow and device transport.
Real hardware timing and output transitions have not been exercised by these tests.

Arrival-histogram revision:
PMTA/PMTC retain all in-range stopwatch arrivals (0..119 bins), even below their
cutoffs. Coincidence and herald eligibility still require both respective cutoffs.
Decay counts, rates, per-attempt probabilities and fits still use the cutoff tails.
No individual photon-pair timing list or accepted-event timing record is added.
The fixed FIFO size remains 163 records. New results use archive schema 2;
older schema-1 results remain readable, but their pre-cutoff arrivals were not
recorded and cannot be reconstructed.
