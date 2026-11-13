"""Coalesce live plots; numerical fitting never runs on the GUI thread."""
from concurrent.futures import ThreadPoolExecutor
from PyQt5 import QtCore
from labremote.entanglement.plotting import decay_fits,EntanglementPlot

_pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='decay-fit')

def prepare(data,settings):
    last=data.get('latest') or dict(a=[0]*120,c=[0]*120)
    return dict(accumulated=decay_fits(data,settings),latest_batch=decay_fits(last,settings))

class EntanglementView(QtCore.QObject):
    def __init__(self,widget,figure,canvas,on_error):
        super().__init__(widget)
        self.widget,self.figure,self.canvas,self.on_error=widget,figure,canvas,on_error
        self.pending=None;self.active=None;self.future=None;self.plot=None
        self.timer=QtCore.QTimer(self);self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick);self.timer.start()

    def submit(self,data,settings):
        self.pending=(data,settings)

    def tick(self):
        if not self.widget.isVisible():return
        if self.future is not None:
            if not self.future.done():return
            data,settings=self.active
            try:
                fits=self.future.result()
                if self.plot is None or self.plot.config!=settings:
                    self.plot=EntanglementPlot(self.figure,settings)
                self.plot.update(data,prepared_fits=fits);self.canvas.draw_idle()
            except Exception as exc:self.on_error('결과 표시 오류: '+str(exc))
            self.future=None;self.active=None
        if self.pending is not None:
            self.active=self.pending;self.pending=None
            self.future=_pool.submit(prepare,*self.active)

    def stop(self):
        self.timer.stop();self.pending=None
        if self.future is not None:self.future.cancel()
