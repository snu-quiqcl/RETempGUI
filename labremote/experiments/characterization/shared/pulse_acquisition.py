"""One queue operation for Ramsey or SPAM; FPGA only, including cleanup."""
import time
from labremote.runtime.errors import OperationCancelled
from labremote.experiments.characterization.rabi.model import hardware
from labremote.experiments.characterization.rabi.acquisition import cleanup

def run(controller,kind,c,cancelled,on_rows,on_record):
    controller._idle();d=controller.device
    def check():
        if cancelled.is_set():raise OperationCancelled(kind+' cancelled')
    def length():
        n=d.fifo_data_length()
        if type(n) is not int or not 0<=n<=65535:raise RuntimeError('Invalid FIFO length')
        return n
    def collect(program,expected,batch,condition,consume,deadline=None,offset=0):
        check();stale=length()
        while stale:
            check();size=min(500,stale);d.read_fifo_data(size);stale-=size
        program.program(show=False,target=d);check();d.auto_mode();d.start_sequencer()
        received=0
        if deadline is None:deadline=time.monotonic()+c['timeout_s']
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
                archived=[[r[0]+offset if type(r[0]) is int else r[0],*r[1:]] for r in rows] if offset else rows
                on_rows(batch,condition,archived,valid)
                if not valid:raise RuntimeError('Unexpected '+kind+' FIFO indices/tag/success count')
                consume(rows,received,True);received+=size;available-=size
            if state=='stopped':break
            time.sleep(.001)
        if received!=expected:raise RuntimeError(f'Missing {kind} FIFO rows: {received}/{expected}')
    try:
        check();cleanup(controller,c['roles']);h=hardware(c['roles'])
        if kind in ('ramsey','spin_echo','initialization'):
            if kind=='spin_echo':
                from labremote.experiments.characterization.spin_echo.sequence import build_program
            elif kind=='ramsey':
                from labremote.experiments.characterization.ramsey.sequence import build_program
            else:
                from labremote.experiments.characterization.initialization.sequence import build_program
            records={}
            def consume(rows,received,apply):
                if not apply:return all(r[0]==(received+i)%c['N_average'] and r[1]==(received+i)//c['N_average'] and r[3]==5 for i,r in enumerate(rows))
                changed=set()
                for r in rows:
                    point=records.setdefault(r[1],dict(index=r[1],counts=[],complete=False));point['counts'].append(r[2]);point['complete']=len(point['counts'])==c['N_average'];changed.add(r[1])
                for index in sorted(changed):on_record(records[index])
            collect(build_program(c,h),c['N_average']*(c['max_precession_count'] if kind in ('ramsey','spin_echo') else c['N_init_control']),-1,-1,consume)
        else:
            from labremote.experiments.characterization.spam.sequence import build_program
            for batch in range(c['N_repeat']):
                for condition in (0,1):
                    if c.get('detector_count',1)==2:
                        record=dict(index=batch*2+condition,batch=batch,condition=condition,attempts=c['N_average'],successes=0,received_rows=0,counts={'PMT':[],'PMT2':[]},complete=False)
                        deadline=time.monotonic()+c['timeout_s']
                        # Two words per shot; preserve the requested shot count and condition order.
                        for offset in range(0,c['N_average'],512):
                            sub=dict(c,N_average=min(512,c['N_average']-offset))
                            def consume(rows,received,apply):
                                if not apply:return all(r[0]==received+i and r[3]==11 for i,r in enumerate(rows))
                                record['counts']['PMT'].extend(r[1] for r in rows)
                                record['counts']['PMT2'].extend(r[2] for r in rows)
                                record['received_rows']+=len(rows);record['successes']=record['received_rows']
                                record['complete']=record['received_rows']==c['N_average'];on_record(record)
                            collect(build_program(condition,sub,h),sub['N_average'],batch,condition,consume,deadline,offset)
                        continue
                    record=dict(index=batch*2+condition,batch=batch,condition=condition,attempts=c['N_average'],successes=None,received_rows=0,counts=[],complete=False)
                    def consume(rows,received,apply):
                        success=record['successes'] if record['successes'] is not None else rows[0][0]
                        if not apply:return 0<=success<=c['N_average'] and all(r[0]==success and r[1]==received+i and r[3]==10 for i,r in enumerate(rows))
                        record['successes']=success;record['counts'].extend(r[2] for r in rows if r[1]<success)
                        record['received_rows']+=len(rows);record['complete']=record['received_rows']==c['N_average'];on_record(record)
                    collect(build_program(condition,c,h),c['N_average'],batch,condition,consume)
    except Exception as original:
        try:cleanup(controller,c['roles'])
        except Exception as exc:raise ConnectionError(f'{kind} FPGA cleanup failed: {exc}; original: {original}') from exc
        raise
    else:
        try:cleanup(controller,c['roles'])
        except Exception as exc:raise ConnectionError(f'{kind} FPGA cleanup failed: {exc}') from exc
