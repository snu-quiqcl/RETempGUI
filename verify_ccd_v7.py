"""Offscreen GUI smoke and timing report using only a synthetic camera."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import time
from pathlib import Path
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from labremote.ui.main_window import Window
from labremote.ui.theme import apply_theme
from labremote.config.settings import DEFAULTS
from copy import deepcopy
from unittest.mock import patch


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_theme(app)
    cfg = deepcopy(DEFAULTS)
    cfg['ccd_options'] = {'backend': 'Dummy'}
    window = Window(cfg)
    panel = window.ccd_tab
    output = Path(__file__).resolve().parent / 'verification_v7'
    output.mkdir(exist_ok=True)
    try:
        window.show()
        window.device_tabs.setCurrentWidget(panel)
        info = panel.worker.submit('connect', {'backend': 'Dummy', 'dummy_shape': (1040, 1392)}).wait(20)
        app.processEvents()
        panel.api.configure_detection(target=3).wait(2)
        panel.api.configure(exposure_ms=30).wait(2)
        panel.api.start_acquisition().wait(2)
        wait = panel.api.wait_for_ions(3, consecutive_frames=3, timeout_s=5)
        ages, analyses, event_gaps, frames = [], [], [], set()
        deadline = time.monotonic()+3
        previous = time.perf_counter()
        while time.monotonic() < deadline:
            app.processEvents()
            now = time.perf_counter()
            event_gaps.append((now-previous)*1000); previous = now
            snapshot = panel.worker.latest_preview()
            if snapshot and snapshot['frame_id'] not in frames:
                frames.add(snapshot['frame_id'])
                ages.append((time.perf_counter_ns()-snapshot['received_ns'])/1e6)
                analyses.append((snapshot['analyzed_ns']-snapshot['received_ns'])/1e6)
            time.sleep(.005)
        result = wait.wait(1)
        # Exercise real Qt event delivery through the main application's wheel filter.
        view = panel.canvas.getViewBox()
        viewport = panel.canvas.viewport()
        center = panel.canvas.mapFromScene(view.mapToScene(view.boundingRect().center()))
        width_before = view.viewRange()[0][1]-view.viewRange()[0][0]
        scroll_before = window.scroll.verticalScrollBar().value()
        wheel = QtGui.QWheelEvent(QtCore.QPointF(center), QtCore.QPointF(viewport.mapToGlobal(center)),
                                 QtCore.QPoint(), QtCore.QPoint(0, 120), QtCore.Qt.NoButton,
                                 QtCore.Qt.NoModifier, QtCore.Qt.ScrollUpdate, False)
        app.sendEvent(viewport, wheel); app.processEvents()
        width_wheel = view.viewRange()[0][1]-view.viewRange()[0][0]
        assert width_wheel < width_before, 'Wheel did not zoom CCD image'
        assert window.scroll.verticalScrollBar().value() == scroll_before, 'Wheel scrolled the main window'
        start = center-QtCore.QPoint(80, 80)
        end = center+QtCore.QPoint(80, 80)
        for event_type, point, button, buttons in (
            (QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.MiddleButton, QtCore.Qt.MiddleButton),
            (QtCore.QEvent.MouseMove, center, QtCore.Qt.NoButton, QtCore.Qt.MiddleButton),
            (QtCore.QEvent.MouseMove, end, QtCore.Qt.NoButton, QtCore.Qt.MiddleButton),
            (QtCore.QEvent.MouseButtonRelease, end, QtCore.Qt.MiddleButton, QtCore.Qt.NoButton)):
            event = QtGui.QMouseEvent(event_type, QtCore.QPointF(point),
                QtCore.QPointF(viewport.mapToGlobal(point)), button, buttons, QtCore.Qt.NoModifier)
            app.sendEvent(viewport, event); app.processEvents(); time.sleep(.03)
        width_drag = view.viewRange()[0][1]-view.viewRange()[0][0]
        assert width_drag < width_wheel, 'Middle-button rectangle drag did not zoom'
        zoom_range = view.viewRange()
        for _ in range(8): app.processEvents(); time.sleep(.02)
        assert np.allclose(view.viewRange(), zoom_range), 'Live frames reset user zoom'
        assert panel.canvas.mapToGlobal(QtCore.QPoint()).x()+panel.canvas.width() <= panel.controls_scroll.mapToGlobal(QtCore.QPoint()).x()
        panel.canvas.autoRange(); app.processEvents()
        window.detail_windows['CCD'].grab().save(str(output/'ccd_tab.png'))
        panel.controls_scroll.ensureWidgetVisible(panel.oven_panel)
        app.processEvents()
        window.detail_windows['CCD'].grab().save(str(output/'ccd_oven_panel.png'))
        # Switching tabs must not stop analysis or workflow conditions.
        window.detail_windows['CCD'].close()
        assert not panel.isVisible(), 'Closing CCD detail window must hide it'
        assert panel.worker.available, 'Hiding the CCD window disconnected the camera'
        window.device_tabs.setCurrentWidget(window.workflow_tab)
        app.processEvents()
        hidden = panel.api.wait_for_ions(3, consecutive_frames=3, timeout_s=3).wait(4)
        panel.api.stop_acquisition().wait(2)
        with patch('labremote.ui.main_window.save_settings'):
            window.close()
            close_deadline = time.monotonic()+10
            while window._running() and time.monotonic() < close_deadline:
                app.processEvents(); time.sleep(.01)
            app.processEvents()
            assert not window._running(), 'Main window failed to stop all workers'
        def stats(values):
            return {'median_ms': float(np.median(values)), 'p95_ms': float(np.percentile(values, 95)), 'max_ms': float(max(values))}
        report = {'backend': 'Dummy', 'shape': info['shape'], 'displayed_samples': len(frames),
                  'read_to_preview_poll': stats(ages), 'read_and_analysis': stats(analyses),
                  'gui_event_loop_gap': stats(event_gaps), 'ion_result': result,
                  'hidden_tab_result': hidden, 'closed_cleanly': True,
                  'layout': 'image left, controls right', 'wheel_zoom': True,
                  'middle_drag_zoom': True, 'live_zoom_preserved': True,
                  'note': 'Synthetic timing only. Does not measure camera exposure, USB, SDK, physical display, or real hardware latency.'}
        (output/'ccd_smoke.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
    finally:
        # Avoid persisting test-only defaults into the user's copied settings.
        window.workflow_tab.shutdown()
        window.discovery_worker.shutdown()
        for p in window._panels(): p.shutdown()
        window.discovery_worker.wait(5000)
        for p in window._panels():
            worker = p.worker
            if hasattr(worker, 'wait'): worker.wait(8000)
        window.hide()
        # Drain Qt-owned objects while QApplication is still alive, rather than
        # letting pyqtgraph/event filters be destroyed at interpreter shutdown.
        app.removeEventFilter(window.wheel_filter)
        for timer in window.findChildren(QtCore.QTimer):timer.stop()
        for worker in {p.worker for p in window._panels()}:
            worker.deleteLater()
        window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        app.processEvents()


if __name__ == '__main__': main()
