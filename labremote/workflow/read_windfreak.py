"""Read-only workflow for connected Windfreak instruments."""
def main(devices):
    for name in devices.names():
        rf = devices.windfreak(name, channel='A')
        rf.acquire('channel_A.frequency_hz').wait()
        rf.acquire('channel_A.power_dbm').wait()
