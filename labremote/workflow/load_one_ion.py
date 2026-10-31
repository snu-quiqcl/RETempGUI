"""CCD/oven devices must be connected first. target=1 means at least one ion."""
def main(devices):
    result=devices.ccd().load_oven(
        isotope=171, shutter='shutter_2',
        threshold=1000, min_area=3, target=1, consecutive_frames=3,
    ).wait()
    # The loader handles fresh CCD frames, ramp up/down, 600 s timeout,
    # cancellation, PSU OFF and shutter CLOSE. Failure raises instead of continuing.
    print('Ion detected; oven cleanup verified:',result)
