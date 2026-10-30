"""Connect CCD in its tab first; Dummy provides three bright test spots."""


def main(devices):
    ccd = devices.ccd('ccd_local')
    ccd.configure_detection(threshold=1000, min_area=3, target=3).wait()
    ccd.start_acquisition().wait()
    try:
        result = ccd.wait_for_ions(target=3, consecutive_frames=3, timeout_s=60).wait()
        print('Ion condition satisfied:', result)
        # Next experiment step goes here. A true condition does not implicitly
        # switch an oven, shutter or flip mirror; command those devices explicitly.
    finally:
        # Cleanup can run even after this workflow was cancelled or failed.
        ccd.stop_acquisition().wait()
