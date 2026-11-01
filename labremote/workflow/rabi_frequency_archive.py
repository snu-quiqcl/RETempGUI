"""External MW frequency sweep; each Rabi operation itself controls only FPGA.

Edit rabi_frequency_sweep.local.json before running. MW output/power/reference
must already be set externally. Output is never toggled here, including Stop.
"""
import math
from pathlib import Path
from labremote.characterization import config,rabi
from labremote.characterization.archive import ExperimentArchive,utc


def execute(devices,recipe,*,workflow_file=None):
    if recipe.get('schema_version')!=1:raise ValueError('Invalid sweep recipe version')
    frequencies=recipe['frequencies_hz'];settle=recipe['settle_s']
    if not isinstance(frequencies,list) or not frequencies:raise ValueError('Supply frequency list')
    for frequency in frequencies:rabi.validate_frequency(frequency)
    if any(f is None for f in frequencies):raise ValueError('Frequency must not be null')
    if isinstance(settle,bool) or not isinstance(settle,(int,float)) or not math.isfinite(settle) or settle<0:raise ValueError('Invalid settling time')
    settings=rabi.validate(recipe['rabi_settings']);chamber=settings['chamber']
    fpga=devices.fpga(recipe['fpga']);mw=devices.anapico(recipe['microwave'])
    with ExperimentArchive(recipe['directory'],recipe=recipe,external_conditions=recipe.get('external_conditions'),workflow_file=workflow_file) as archive:
        for frequency in frequencies:
            point=archive.begin_point(dict(frequency_hz_requested=frequency,chamber=chamber))
            mw.set_frequency(frequency).wait()
            devices.wait(settle)
            # Values are acquired only once per frequency, not every FPGA point.
            actual=mw.acquire('frequency').wait();output=mw.acquire('output').wait()
            config.save(point/'microwave_readback.json',dict(acquired_utc=utc(),requested_frequency_hz=frequency,acquired_frequency_hz=actual,acquired_output=output,output_control='external'))
            if output not in (True,1,'ON','on'):raise RuntimeError('Enable microwave output externally before measurement')
            rabi.validate_frequency(actual)
            if actual is None:raise ValueError('Missing frequency readback')
            result=fpga.run_rabi(chamber,settings=settings,directory=point,frequency_hz=actual).wait()
            archive.finish_point(point,result)
        print('Saved frequency series:',archive.folder)
        return archive.folder


def main(devices):
    path=config.ROOT/'rabi_frequency_sweep.local.json'
    if not path.exists():
        raise ValueError('Copy rabi_frequency_sweep.json to rabi_frequency_sweep.local.json and configure it first')
    recipe=config.read(path)
    execute(devices,recipe,workflow_file=__file__)
