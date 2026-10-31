from pathlib import Path
import labremote

SEQUENCE_FILE=Path(labremote.__file__).resolve().parent/'sequence_examples'/'pmt_exposure.py'

def main(devices):
    devices.ccd().load_oven(
        isotope=171, shutter='shutter_2',
        threshold=1000, min_area=3, target=1, consecutive_frames=3,
    ).wait()
    # Reached only after ion detection AND confirmed oven shutdown.
    # Timeout, cancellation or cleanup failure prevents FPGA execution.
    result=devices.fpga('fpga_local').run_sequence_file(
        SEQUENCE_FILE, parameters={'channel':0,'exposure_ms':100},
        timeout_s=10, max_rows=16,
    ).wait()
    print(result)
