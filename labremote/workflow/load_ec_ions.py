"""Connect oven devices and Thorcam in CCD first; verify shutter mapping there."""
def main(devices):
    from labremote.devices.oven.settings import load_settings
    config = load_settings()
    result = devices.ccd().load_oven(
        171, shutter=config['shutter'], shutter_confirmed=config['shutter_confirmed'],
        threshold=1000, min_area=3, target=1, consecutive_frames=3,
    ).wait()
    print(result)  # Returns only after PSU OFF and shutter CLOSED are verified.
