"""Edit device names and target values before running."""


def main(devices):
    rf = devices.dds('dds4', channel=1)
    # DDS acquire returns the last transmitted setting, not measured RF.
    current_hz = rf.acquire('ch1.frequency_hz').wait()
    rf.set_frequency(100e6 if current_hz is None else current_hz).wait()
    rf.set_phase(0).wait()
    rf.set_vva(0).wait()
    # rf.on().wait()
    # rf.all_off().wait()
