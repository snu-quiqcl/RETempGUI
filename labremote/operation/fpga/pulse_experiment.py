"""One queue operation for Ramsey or SPAM; FPGA only, including cleanup."""
import time
from labremote.runtime.errors import OperationCancelled
from labremote.characterization.rabi import hardware
from .rabi import cleanup

def run(controller,kind,c,cancelled,on_rows,on_record):
    controller._idle();d=controller.device
    def check():
        if cancelled.is_set():raise OperationCancelled(kind+' cancelled')
    def length():
        n=d.fifo_data_length()
        if type(n) is not int or not 0<=n<=65535:raise RuntimeError('Invalid FIFO length')
        return n
    def collect(program,expected,batch,condition,consume):
        check();stale=length()
        while stale:
            check();size=min(500,stale);d.read_fifo_data(size);stale-=size
        program.program(show=False,target=d);check();d.auto_mode();d.start_sequencer()
        received=0;deadline=time.monotonic()+c['timeout_s']
        while True:
            check()
            if time.monotonic()>deadline:raise TimeoutError(kind+' acquisition timeout')
            state=d.sequencer_running_status()
            if state not in ('running','stopped'):raise RuntimeError('Invalid sequencer status')
            available=length()
            while available:
                check()
                if time.monotonic()>deadline:raise TimeoutError(kind+' FIFO timeout')
                size=min(500,available);rows=d.read_fifo_data(size)
                if not isinstance(rows,list) or len(rows)!=size or any(not isinstance(r,(list,tuple)) or len(r)!=4 for r in rows):raise RuntimeError('Malformed FIFO rows')
                valid=received+size<=expected and all(all(type(v) is int and 0<=v<=65535 for v in r) for r in rows)
                valid=valid and consume(rows,received,False)
                on_rows(batch,condition,rows,valid)
                if not valid:raise RuntimeError('Unexpected '+kind+' FIFO indices/tag/success count')
                consume(rows,received,True);received+=size;available-=size
            if state=='stopped':break
            time.sleep(.001)
        if received!=expected:raise RuntimeError(f'Missing {kind} FIFO rows: {received}/{expected}')
    try:
        check();cleanup(controller,c['roles']);h=hardware(c['roles'])
        if kind in ('ramsey','initialization'):
            if kind=='ramsey':
                from labremote.characterization.ramsey_sequence import build_program
            else:
                from labremote.characterization.initialization_sequence import build_program
            records={}
            def consume(rows,received,apply):
                if not apply:return all(r[0]==(received+i)%c['N_average'] and r[1]==(received+i)//c['N_average'] and r[3]==5 for i,r in enumerate(rows))
                changed=set()
                for r in rows:
                    point=records.setdefault(r[1],dict(index=r[1],counts=[],complete=False));point['counts'].append(r[2]);point['complete']=len(point['counts'])==c['N_average'];changed.add(r[1])
                for index in sorted(changed):on_record(records[index])
            collect(build_program(c,h),c['N_average']*(c['max_precession_count'] if kind=='ramsey' else c['N_init_control']),-1,-1,consume)
        else:
            from labremote.characterization.spam_sequence import build_program
            for batch in range(c['N_repeat']):
                for condition in (0,1):
                    record=dict(index=batch*2+condition,batch=batch,condition=condition,attempts=c['N_average'],successes=None,received_rows=0,counts=[],complete=False)
                    def consume(rows,received,apply):
                        success=record['successes'] if record['successes'] is not None else rows[0][0]
                        if not apply:return 0<=success<=c['N_average'] and all(r[0]==success and r[1]==received+i and r[3]==10 for i,r in enumerate(rows))
                        record['successes']=success;record['counts'].extend(r[2] for r in rows if r[1]<success)
                        record['received_rows']+=len(rows);record['complete']=record['received_rows']==c['N_average'];on_record(record)
                    collect(build_program(condition,c,h),c['N_average'],batch,condition,consume)
    except Exception as original:
        try:cleanup(controller,c['roles'])
        except Exception as exc:raise RuntimeError(f'{kind} FPGA cleanup failed: {exc}; original: {original}') from exc
        raise
    else:
        try:cleanup(controller,c['roles'])
        except Exception as exc:raise RuntimeError(f'{kind} FPGA cleanup failed: {exc}') from exc
