"""RF ON only: already-enabled output is left unchanged."""


def main(devices):
    rf = devices.windfreak('synthhd_760', channel='A')

    # Already ON: read output state and finish without writing.
    # OFF: assign the configured low power, then enable output (with readback).
    rf.on().wait()

    # Optional: this is a separate operation and DOES change power even if ON.
    # rf.set_power(-30.0).wait()
