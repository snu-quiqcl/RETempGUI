"""Entry point: combined modular QCoDeS InstrumentServer GUI."""

def main():
    from labremote.configuration.startup import require_local_configuration
    try:
        require_local_configuration()
    except (FileNotFoundError, ValueError) as exc:
        from PyQt5.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, 'Restore local configuration', str(exc))
        return 1
    from labremote.ui.main_window import main as run_gui
    return run_gui()

if __name__ == '__main__':
    raise SystemExit(main())
