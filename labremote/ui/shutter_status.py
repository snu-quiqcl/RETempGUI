"""Paint confirmed relay state without issuing device reads."""
from labremote.runtime.parameters import LIBRARY

def shutter_status(worker, name):
    if worker.ps is None or worker.connection_error or worker.io_fault:return None
    value=LIBRARY.read((worker._execution_device,name))
    if value.quality!='valid' or value.error or value.verification in ('pending','failed','mismatch'):return None
    return value.observed if value.observed in ('OPEN','CLOSED') else None

def show_shutter(label, worker, name, open_button=None, close_button=None):
    value=shutter_status(worker,name)
    text='OPEN · 열림' if value=='OPEN' else 'CLOSED · 닫힘' if value=='CLOSED' else '위치 미확인'
    color='#238636' if value=='OPEN' else '#b42318' if value=='CLOSED' else '#616161'
    label.setText(name+' · '+text)
    label.setStyleSheet('QLabel { color: white; background-color: '+color+'; padding: 5px; border-radius: 4px; }')
    for button,state,active_color in ((open_button,'OPEN','#238636'),(close_button,'CLOSED','#b42318')):
        if button is not None:
            button.setProperty('shutterState',value)
            button.setStyleSheet('QPushButton { color: white; background-color: '+(active_color if value==state else '#616161')+'; padding: 6px; border-radius: 4px; }')
    return value
