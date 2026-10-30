"""Read all four displayed MSO7054 channels through the common API."""


def main(devices):
    scope = devices.mso7054('mso7054')
    waveforms = scope.read_waveforms(('CH1', 'CH2', 'CH3', 'CH4')).wait()
    ch1_vpp = scope.acquire('ch1_vpp').wait()
    # capture = scope.start_waveform(('CH1', 'CH4'), interval_s=1)
    # capture.wait()  # Runs until workflow cancellation or acquisition failure.
