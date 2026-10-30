"""Connect the device in its tab before running this workflow."""


def main(devices):
    mdt = devices.mdt('mdt693b')
    voltage = mdt.acquire('x.voltage').wait()
    print('MDT X:', voltage, 'V')
    # mdt.set_voltage('X', 20.0).wait()
