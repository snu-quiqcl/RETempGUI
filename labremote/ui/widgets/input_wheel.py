"""Wheel gestures scroll forms, never silently edit instrument settings."""
from PyQt5 import QtCore, QtGui, QtWidgets as W


class InputWheelGuard(QtCore.QObject):
    def eventFilter(self, watched, event):
        if event.type() != QtCore.QEvent.Wheel or not isinstance(watched, W.QWidget):
            return False
        control = watched
        while control is not None:
            # Open dropdown lists, tables and plots keep their own scrolling.
            if isinstance(control, W.QAbstractScrollArea):
                return False
            if isinstance(control, (W.QComboBox, W.QAbstractSpinBox, W.QSlider)):
                break
            control = control.parentWidget()
        if control is None:
            return False
        if isinstance(control, W.QComboBox) and control.view().isVisible():
            self.forward(control.view().viewport(), event)
        else:
            parent = control.parentWidget()
            while parent is not None:
                if isinstance(parent, W.QAbstractScrollArea):
                    bars = (parent.verticalScrollBar(), parent.horizontalScrollBar())
                    before = tuple(bar.value() for bar in bars)
                    self.forward(parent.viewport(), event)
                    if tuple(bar.value() for bar in bars) != before:
                        break
                # Do not scroll a dialog's owner window behind the dialog.
                if parent.isWindow():
                    break
                parent = parent.parentWidget()
        # Consume even when there is no scroll range, or the input has focus.
        event.accept()
        return True

    @staticmethod
    def forward(viewport, event):
        position = QtCore.QPointF(viewport.mapFromGlobal(event.globalPos()))
        forwarded = QtGui.QWheelEvent(position, event.globalPosF(), event.pixelDelta(),
            event.angleDelta(), event.buttons(), event.modifiers(), event.phase(), event.inverted())
        W.QApplication.sendEvent(viewport, forwarded)


def install_input_wheel_guard():
    app = W.QApplication.instance()
    guard = getattr(app, '_labremote_input_wheel_guard', None)
    if guard is None:
        guard = InputWheelGuard(app)
        app._labremote_input_wheel_guard = guard
        app.installEventFilter(guard)
    return guard
