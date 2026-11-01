"""One persistent detail window per device group; closing only hides it."""
from PyQt5 import QtCore,QtWidgets

class DetailWindow(QtWidgets.QMainWindow):
    def __init__(self,title,content,owner):
        super().__init__(owner,QtCore.Qt.Window)
        self.owner=owner;self.allow_close=False
        self.setWindowTitle('RETempGUI · '+title);self.resize(1280,900)
        self.scroll=QtWidgets.QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setWidget(content)
        self.setCentralWidget(self.scroll)
        from .main_window import WheelToMainScroll
        self.wheel_filter=WheelToMainScroll(self.scroll,content,self)
        QtWidgets.QApplication.instance().installEventFilter(self.wheel_filter)
    @property
    def _closing(self):return self.owner._closing
    def open(self):
        if self.owner._closing:return
        self.showNormal();self.raise_();self.activateWindow()
    def closeEvent(self,event):
        if self.allow_close:event.accept()
        else:self.hide();event.ignore()

class MainTabs(QtWidgets.QTabWidget):
    """Legacy programmatic selection raises a detached detail view, without duplicating it."""
    def __init__(self,parent=None):
        super().__init__(parent);self.detail_windows={}
    def setCurrentWidget(self,widget):
        window=self.detail_windows.get(widget)
        if window is not None:window.open()
        else:super().setCurrentWidget(widget)
