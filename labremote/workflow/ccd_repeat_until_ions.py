"""Repeat a step until a fresh ion condition succeeds; always stop CCD on exit."""
from labremote.runtime.errors import OperationCancelled


def main(devices):
    ccd = devices.ccd()
    ccd.configure_detection(threshold=1000, target=3).wait()
    ccd.start_acquisition().wait()
    condition = ccd.wait_for_ions(target=3, consecutive_frames=3, timeout_s=60)
    try:
        while not condition.done.is_set():
            # Place a bounded, cancellable experiment step here.
            # In-flight device operations finish according to their own stop policy.
            try:
                devices.wait(0.05)
            except OperationCancelled:
                # A failed ion wait also cancels the workflow group. Preserve its
                # original timeout/camera error instead of reporting only cancellation.
                if condition.done.is_set(): condition.wait()
                raise
        result = condition.wait()  # Propagate timeout, analysis failure or disconnect.
        print('Continue with next step:', result)
    finally:
        ccd.stop_acquisition().wait()
