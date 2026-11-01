"""One persistent detail window per device group; closing only hides it."""
from PyQt5 import QtCore,QtWidgets

class DetailWindow(QtWidgets.QMainWindow):
    def __init__(self,title,content,owner):
        super().__init__(None,QtCore.Qt.Window)
        # Native owned windows stay above their owner on Windows. Use a true
        # independent top-level window; the owner still manages shutdown.
        self.owner=owner;self.allow_close=False
        owner.destroyed.connect(self.deleteLater)
        self.setWindowTitle(title);self.resize(1280,900)
        self.scroll=QtWidgets.QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setWidget(content)
        self.setCentralWidget(self.scroll)
        home=self.menuBar().addAction('메인창')
        home.triggered.connect(self.open_main)
        from .main_window import WheelToMainScroll
        self.wheel_filter=WheelToMainScroll(self.scroll,content,self)
        QtWidgets.QApplication.instance().installEventFilter(self.wheel_filter)
    def open_main(self):
        if self.owner._closing:return
        self.owner.showNormal();self.owner.raise_();self.owner.activateWindow()

    @property
    def _closing(self):return self.owner._closing
    def open(self):
        if self.owner._closing:return
        self.showNormal();self.raise_();self.activateWindow()
    def closeEvent(self,event):
        if self.allow_close:
            QtWidgets.QApplication.instance().removeEventFilter(self.wheel_filter)
            event.accept()
        else:self.hide();event.ignore()

class MainTabs(QtWidgets.QTabWidget):
    """Legacy programmatic selection raises a detached detail view, without duplicating it."""
    def __init__(self,parent=None):
        super().__init__(parent);self.detail_windows={}
    def setCurrentWidget(self,widget):
        window=self.detail_windows.get(widget)
        if window is not None:window.open()
        else:super().setCurrentWidget(widget)
