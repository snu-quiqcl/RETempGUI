from pathlib import Path
import labremote

# Replace with an absolute file path on the UI PC, e.g. Path(r"D:\sequences\my_sequence.py").
SEQUENCE_FILE=Path(labremote.__file__).resolve().parent/'sequence_examples'/'pmt_exposure.py'

def main(devices):
    # Connect fpga_local in the FPGA tab before running this workflow.
    result=devices.fpga('fpga_local').run_sequence_file(
        SEQUENCE_FILE, parameters={'channel':0,'exposure_ms':100},
        timeout_s=10, max_rows=16,
    ).wait()
    # This example emits [channel, exposure_ticks, count, 10].
    print(result['rows'])
