"""Edit device names and target values before running."""


def main(devices):
    rf = devices.anapico('apsyn420_7g')
    current_hz = rf.acquire('frequency').wait()
    rf.set_frequency(current_hz).wait()
    rf.set_phase(0).wait()
    # rf.on().wait()
    # rf.off().wait()
