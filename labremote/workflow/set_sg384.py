"""Edit device names and target values before running."""


def main(devices):
    rf = devices.sg384('sg384_EA', port='N')
    current_power_dbm = rf.acquire('n_power_dbm').wait()
    rf.set_power(current_power_dbm).wait()
    rf.set_frequency(100e6).wait()
    # rf.on().wait()
    # rf.off().wait()
