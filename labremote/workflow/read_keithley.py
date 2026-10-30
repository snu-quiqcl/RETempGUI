"""Read Keithley CH1; uncomment writes only for intended setpoints."""


def main(devices):
    supply = devices.keithley('keithley_ps', channel=1)
    volts = supply.acquire('ch1.voltage').wait()
    amps = supply.acquire('ch1.current').wait()
    # supply.set_current(0.1).wait()
    # supply.set_voltage(1).wait()
    # supply.on().wait()
    # supply.off().wait()
