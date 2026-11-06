"""Open this file in the existing Workflow tab. It controls real outputs when run."""
from pathlib import Path
from labremote.data_paths import DATA_ROOT


def main(devices):
    dac = devices.dac('dac_ea')  # Server instrument name; EC uses dac_ec.
    # Connect EA from the main equipment configuration before starting.
    # Load does not transmit. Mapping lives on the client; Initialize uploads calibration offsets.
    preset = dac.load_preset(DATA_ROOT/'dac/EA/presets/loading.json')
    dac.initialize(preset.by_id, use_ldac=True).wait()
    # To initialize all 32 physical channels to calibrated zero instead:
    # dac.initialize(use_ldac=True).wait()
    sequence = dac.load_sequence(DATA_ROOT/'dac/EA/sequences/transport.csv', use_ldac=True)
    result = dac.run_sequence(sequence).wait()
    # Failure/cancellation raises here and propagates to workflow/queue policy.
    # Add RF/FPGA operations with the existing APIs after this completed job.
    return result
