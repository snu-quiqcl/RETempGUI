"""Run archive loading/reanalysis off the GUI thread; deliver only the latest request."""
from concurrent.futures import ThreadPoolExecutor
from PyQt5 import QtCore

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='result-read')


class ResultLoader(QtCore.QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.future = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)

    def start(self, read, ready, failed):
        self.cancel()
        self.ready, self.failed = ready, failed
        self.future = _pool.submit(read)
        self.timer.start()

    def cancel(self):
        self.timer.stop()
        if self.future is not None:
            self.future.cancel()
        self.future = None

    def poll(self):
        if self.future is None or not self.future.done():
            return
        future = self.future
        self.future = None
        self.timer.stop()
        try:
            value = future.result()
            self.ready(value)
        except Exception as exc:
            self.failed(str(exc))
