"""Portable path budgets for Queue archives, independent of Windows policy."""
from pathlib import Path
from uuid import uuid4

MAX_PATH_UNITS=259  # Excludes the terminating NUL in legacy Win32 MAX_PATH.


def path_units(path):
    return len(str(Path(path).absolute()).encode('utf-16-le'))//2


def check_path(path, *, reserve=0, label='저장 경로'):
    length=path_units(path)+reserve
    if length>MAX_PATH_UNITS:
        raise ValueError(f'{label}: 저장 경로가 너무 깁니다 ({length}/{MAX_PATH_UNITS}, 하위 파일 여유 포함). '
                         f'Queue 저장 폴더를 C:\\QData처럼 짧게 지정하거나 그룹·항목·FPGA 별명을 줄이세요. 경로: {path}')


def check_queue(folder,plan,steps,output_directories):
    from .workflow_queue import workflow_jobs
    jobs={j['id']:j for j in workflow_jobs(plan['jobs'])}
    check_path(folder/'queue_manifest.json.tmp')
    for step in steps:
        job=jobs[step['job_id']]
        aliases=[p.get('alias','') for p in job.get('fpga_profiles',{}).values()]
        alias_units=max([len(a.encode('utf-16-le'))//2 for a in aliases]+[0])
        # Reserve EA/EC, alias, compact run folder, source filenames and JSON
        # temporary suffixes. Custom workflows can create arbitrary deeper paths.
        reserve=max(72,alias_units+64)
        if job.get('parameters',{}).get('kind')=='SpamScanTab' or 'run_spam_scan' in job.get('source',''):
            reserve+=32+alias_units  # Outer run / grid point / nested SPAM run.
        check_path(folder/output_directories[step['step_id']],reserve=reserve,
                   label=f"{step.get('group_name','Ungrouped')} / {step['name']}")


def compact_run_folder(candidate):
    """Keep standalone names; Queue paths already identify time/group/experiment."""
    from .queue_archive import allocate
    allocated=allocate(candidate)
    if allocated is not None:
        check_path(allocated,reserve=48,label="실험 결과 폴더")
        return allocated
    candidate=Path(candidate)
    for parent in candidate.parents:
        if (parent/'queue_manifest.json').is_file():
            # Independent entropy also handles repeated calls within one workflow.
            result=candidate.with_name('r_'+uuid4().hex[:8])
            check_path(result,reserve=48,label='실험 결과 폴더')
            return result
    return candidate
