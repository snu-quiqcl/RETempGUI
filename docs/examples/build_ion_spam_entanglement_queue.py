"""Generate a GUI-loadable Queue. Run from the project Python environment.

Example:
python docs/examples/build_ion_spam_entanglement_queue.py --repeat 10 \
    --threshold-a 20 --threshold-b 10 --threshold-c 20
Threshold numbers above are syntax examples, not calibrated values.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_plan(root=ROOT, repeat=3, thresholds=(None, None, None), max_attempts=3):
    from labremote.runtime.workflow_queue import freeze_job, make_group, validate_plan
    from labremote.characterization import pulse_experiment
    from labremote.entanglement import config as entanglement
    if type(repeat) is not int or not 1 <= repeat <= 256:
        raise ValueError('repeat must be 1..256 (39 workflows per sweep; 10000-step limit)')
    if type(max_attempts) is not int or not 1 <= max_attempts <= 10000:
        raise ValueError('max_attempts must be 1..10000')
    if len(thresholds) != 3 or any(v is not None and (type(v) is not int or not 1 <= v <= 65535) for v in thresholds):
        raise ValueError('thresholds must be three integers in 1..65535, or None')
    root = Path(root).resolve()
    spam_settings = {chamber: pulse_experiment.load('spam', chamber)
                     for chamber in ('EA', 'EC')}
    base = entanglement.load()
    groups = []
    for basis, phase in [('zz', 0)] + [('mw_detuned', angle) for angle in range(0, 360, 30)]:
        settings = dict(base, basis=basis, phase_magnitude_deg=phase)
        entanglement.validate(settings)
        jobs = [
            freeze_job(root / 'labremote/workflow/ion_check_workflow.py', name='Ion check',
                       parameters=dict(fpga='fpga_local', max_attempts=max_attempts,
                                       exposure_us=1000, settle_us=100, retry_delay_s=0.1,
                                       timeout_s=5, threshold_a=thresholds[0],
                                       threshold_b=thresholds[1], threshold_c=thresholds[2],
                                       sequence_path=str(root / 'labremote/sequences/ion_check_sequence.py'))),
            freeze_job(root / 'labremote/workflow/queue_spam.py', name='SPAM EA -> EC',
                       parameters=dict(fpga='fpga_local', settings=spam_settings)),
            freeze_job(root / 'labremote/workflow/queue_entanglement.py', name='Entanglement',
                       parameters=dict(fpga='fpga_local', settings=settings)),
        ]
        name = 'ZZ' if basis == 'zz' else f'MW detuned {phase} deg'
        groups.append(make_group(jobs, name=name, repeat=repeat, on_failure='stop'))
    return validate_plan(dict(schema_version=2, repeat=1, jobs=groups))


def main():
    from labremote.runtime.workflow_queue import save, expand_steps
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=3, help='N per group, including the first cycle')
    parser.add_argument('--max-attempts', type=int, default=3, help='Ion-check measurements per guard')
    for stage in ('a', 'b', 'c'):
        parser.add_argument(f'--threshold-{stage}', type=int)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'docs/examples/ion_spam_entanglement_sweep.queue.json')
    args = parser.parse_args()
    thresholds = (args.threshold_a, args.threshold_b, args.threshold_c)
    plan = build_plan(repeat=args.repeat, thresholds=thresholds, max_attempts=args.max_attempts)
    save(args.output, plan)
    print(f'Saved {args.output}: 13 groups, {len(expand_steps(plan))} workflow executions')
    if None in thresholds:
        print('Ion thresholds are unset. The GUI can load this file, but the ion guard will stop before acquisition until all thresholds are set.')


if __name__ == '__main__':
    main()
