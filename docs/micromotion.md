# Micromotion: RF-photon correlation and a linear compensation valley

The FPGA device now has a Micromotion tab beside Daily characterization, Decay,
HOM and Entanglement. It uses the already connected FPGA and the selected
connected DAC. It never opens a second COM port, switches manual/auto mode,
or changes external cooling/AOM/laser outputs.

## Measurements

Micromotion contains three separate tabs: **Signal**, **RF–Photon Correlation**,
and **2D Scan**. Each page has its own parameters, Run/Stop buttons, result figure
and last-result state. Only one experiment can use the shared FPGA at a time.
Changing pages does not erase results or stop an acquisition. Stop on any page
stops the active Micromotion job. Apply verification is shown on the Correlation
page while the completed scan and compensation line remain on the 2D Scan page.

1. RF Input Check counts an externally supplied signal over repeated gates.
   Select a separately wired counter-capable input. `ja_2 / SYNC` has a stopwatch
   but no ordinary pulse counter in the current hardware definition. Matching
   counts verifies reception, not phase lock. The reference must remain coherent
   with the trap RF for the correlation scan.
2. Correlation records positive photon-minus-reference time differences in
   1.25 ns bins. Set TRG and PMT to distinct stopwatch-capable physical pins.
   Frequency, target accepted events, repetitions, observation periods and
   point timeout are editable. The target is events times batches; FPGA chunks
   are capped at 30000 accepted events and a finite attempt budget. Missing
   signals cannot create an unbounded hardware loop. Host accumulation is 64 bit.
3. Compensation Scan sweeps L_IN (x) and R_IN (y), updates the two channels with
   the selected LDAC policy, waits for settling, measures, fits and saves each
   completed point. The scan is always 2D. Unmeasured cells remain masked.

Each chamber and page has separately saveable settings under
`labremote/config/operations/micromotion/`, for example `EC.input.local.json`,
`EC.correlation.local.json`, and `EC.scan.local.json` (likewise for EA).
The former `EA.local.json` / `EC.local.json` remain fallbacks until page settings
are saved. Changing one page's parameters does not overwrite another page's
settings; check RF frequency and physical pin selections on each page.
Initial ranges/frequency are examples from the supplied EC script, not detected
hardware values. Configure the actual chamber, frequency, pins and scan range.

## Analysis and selection

The histogram fit uses the actual RF frequency, not padded FIFO length, in
`C + A cos(omega t) + B sin(omega t)`. Bin zero and padding outside the requested
physical observation window are excluded from fitting but preserved in raw data.
Poisson IRLS estimates the harmonic coefficients and propagates their covariance
to `(A/C, B/C)`. Visibility is the length of this vector. Phase near the noise
floor is marked unresolved.

Visibility and TRG-relative phase heatmaps appear side by side in the 2D Scan
tab. Both use L_IN/R_IN axes; clicking either selects the same histogram and
visibility/phase readout. Phase uses a cyclic palette with fixed -180..180 deg
or -pi..pi rad limits; units affect display only. The saved phase and its local
standard error are always radians, with convention `phase = atan2(-B,A)` in
`H(t) = C [1 + visibility*cos(omega*t + phase)]`.

The phase error is propagated from the full quadrature covariance using gradient
`(q_y, -q_x) / |q|^2`. An estimate is marked unresolved if visibility does not
exceed three radial standard errors or phase standard error reaches 60 degrees.
Unresolved measured cells are grey by default; unmeasured cells remain empty.
Unchecking Mask unresolved phase reveals raw estimates, still labelled unreliable.
Near zero amplitude, phase and its linearized uncertainty should not be interpreted
as a resolved physical phase. The phase-across-valley graph uses circular error
intervals split at +/-pi rather than connecting across the wrap boundary.

Old results without phase-error fields remain readable: phase/error/reliability
are derived from their saved quadratures and covariance. The line fit continues
to use quadratures, not wrapped phase. New results include phase SE, reliability
and the reference/unit convention in metadata.

All measured quadratures and their 2x2 covariance matrices enter a weighted
rank-one affine fit `q = q0 + u * (n dot (V-center))`, with unit normal n. Its
minimum defines a line, represented implicitly so vertical lines remain valid.
The display shows the equivalent R_IN/L_IN relation when possible, the valley
floor, reduced chi-square, and local linearized 95% normal confidence band.
The band is conditional on the rank-one model, not a guarantee against drift.

Independent slice fits provide minimum locations with voltage errors. Boundary
minima are excluded. The lower diagnostics show visibility against perpendicular
distance and fitted slice floors along the valley. Heatmap clicks select a
measured cell's histogram. A slider selects a candidate along the fitted segment
inside the measured rectangle; its initial location is the point nearest the
starting voltages. No unique minimum along a flat valley is asserted.

Unidentifiable/out-of-range valleys are not offered for application. Large model
residuals or poorly localized lines produce warnings and disable Apply. Complete
a new scan with unchanged settings and the same selected DAC to Apply selected
compensation + verify. Loaded archives are view-only for voltage application.
Successful verification acquisition retains the candidate; it does not assert
an improvement unless the measured correlation actually supports it.

## Ownership, stop and output files

Both existing worker queues are reserved during a scan. The DAC server's shared
control lease is renewed during FPGA acquisition and settling. The starting
voltage snapshot is taken after lease acquisition. Only L_IN/R_IN are transmitted;
other electrodes and their calibrations remain under the existing DAC API.

Normal scan completion, Stop and failures restore starting L_IN/R_IN and release
the lease. Apply retains the candidate only on successful acquisition; failure or
Stop restores its starting values. If hardware/transport/lease failure prevents
restoration, the result explicitly reports cleanup failure. No voltage readback
is claimed: the DAC state is the server's last-requested state.

Each run has `results.json`, raw FIFO records in `raw_fifo.jsonl`, complete
`point_*.json`, acquired partial point snapshots in `partial_*.json`, and a PNG.
Results include settings, physical input mapping, DAC calibration/configuration,
starting state, harmonic coefficients/covariances, line fit and cleanup status.
An interrupted in-flight FPGA chunk is not counted as a complete measurement.

Offline validation covers synthetic diagonal/vertical valleys and isolated
minima, vendor instruction emulation, missing signals, FIFO validation, worker
reservations, lease renewal, cancellation, restoration and offscreen Qt layout.
Real input wiring, RF reception, stopwatch timing and DAC settling still require
verification on the laboratory hardware.
