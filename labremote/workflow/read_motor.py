"""Connect the device in its tab before running this workflow."""


def main(devices):
    motor = devices.motor('EA_px')
    state = motor.status().wait()
    print('Motor position:', state.get('position'))
    # motor.open().wait()
    # motor.move(1.0).wait()
    # motor.home().wait()
