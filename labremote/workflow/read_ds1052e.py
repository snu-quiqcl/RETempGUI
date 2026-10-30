"""Read scope settings and waveforms through the shared execution handle."""


def main(devices):
    scope = devices.ds1052e('ds1052e_EA')
    time_scale_s = scope.acquire('time_scale').wait()
    waveforms = scope.read_waveforms(('CH1', 'CH2')).wait()
    # Each displayed channel provides time (s) and voltage (V) arrays:
    if 'CH1' in waveforms['traces']:
        times_s, volts = waveforms['traces']['CH1']
    # Explicit settings examples (uncomment to change the scope):
    # scope.configure_horizontal(time_scale_s, 0).wait()
    # scope.configure_vertical('CH1', 1.0, 0).wait()
    # scope.configure_trigger('CH1', 0, slope='POS', sweep='AUTO').wait()
    # scope.run().wait()
    # scope.stop().wait()
