"""Read once; start_monitoring()/stop_monitoring() control the per-device loop."""


def main(devices):
    chiller = devices.thermotek('t257p')
    readings = chiller.read_telemetry().wait()
    # chiller.set_target(20).wait()
    # chiller.start().wait()  # Pump RUN, not monitoring.
    # chiller.stop().wait()   # Pump STOP, not monitoring.
