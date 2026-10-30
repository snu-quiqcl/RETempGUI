"""Acquire + assign example. Edit the target device and values before running."""


def main(devices):
    rf = devices.windfreak('synthhd_760', channel='A')

    # Each wait() finishes the current operation before starting the next one.
    rf.acquire('channel_A.frequency_hz').wait()

    rf.set_frequency(100e6).wait()

    # acquire(...).wait() returns the value read by this request, in dBm.
    current_power_dbm = rf.acquire('channel_A.power_dbm').wait()
    target_power_dbm = current_power_dbm + 1.0
    rf.set_power(target_power_dbm).wait()

    rf.acquire('channel_A.frequency_hz').wait()
    rf.acquire('channel_A.power_dbm').wait()
