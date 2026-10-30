"""Shared DDS-style appearance. No instrument or interaction logic lives here."""
import os
from pathlib import Path

from PyQt5 import QtGui

BACKGROUND = '#101827'
PANEL = '#18273a'
TEXT = '#e1e8f4'
MUTED = '#92a5bd'
ACCENT = '#69dccb'
WARNING = '#f3c46b'
ERROR = '#ff8fa3'

STYLESHEET = '''
QWidget { color: #e1e8f4; }
QMainWindow, QDialog, QScrollArea, QTabWidget::pane { background: #101827; }
QToolTip { color: #e1e8f4; background: #25415c; border: 1px solid #69dccb; padding: 4px; }
QGroupBox { border: 1px solid #35455d; border-radius: 7px; margin-top: 9px; padding-top: 7px; }
QGroupBox::title { subcontrol-origin: margin; left: 9px; padding: 0 4px; color: #69dccb; font-weight: 600; }
QTabWidget::pane { border: 1px solid #35455d; }
QTabBar::tab { background: #18273a; color: #aebfd3; padding: 5px 10px; border: 1px solid #35455d; }
QTabBar::tab:selected { background: #25415c; color: #69dccb; border-bottom: 2px solid #69dccb; }
QTabBar::tab:hover:!selected { background: #21354d; }
QPushButton, QToolButton { background: #254b70; border: 1px solid #396185; border-radius: 5px; padding: 3px 7px; }
QPushButton:hover, QToolButton:hover { background: #34638d; border-color: #69dccb; }
QPushButton:pressed, QToolButton:pressed { background: #173b40; }
QPushButton:checked, QToolButton:checked { background: #20554f; color: #9ef1df; border-color: #69dccb; }
QPushButton[text="RF OFF"], QPushButton[text="OFF"], QPushButton[text="STOP"],
QPushButton[text="Abort"], QPushButton[text="Immediate OFF"], QPushButton[text="Ramp OFF"],
QPushButton[text="Output OFF"] {
    background: #683445; border-color: #91485d; color: #ffe2e8; }
QPushButton:disabled, QToolButton:disabled { background: #202c3b; color: #78879b; border-color: #2c394b; }
QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
    background: #18273a; color: #e1e8f4; border: 1px solid #425675;
    border-radius: 4px; padding: 2px 4px; selection-background-color: #285e76;
    selection-color: #ffffff;
}
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus { border-color: #69dccb; }
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled { background: #172131; color: #78879b; border-color: #2c394b; }
QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled { color: #78879b; }
QComboBox QAbstractItemView { background: #18273a; color: #e1e8f4; selection-background-color: #285e76; }
QAbstractItemView { background: #131f30; alternate-background-color: #1b2c40; color: #e1e8f4;
    border: 1px solid #35455d; selection-background-color: #285e76; selection-color: #ffffff; }
QHeaderView::section, QTableCornerButton::section { background: #21354d; color: #b9cce6;
    border: 1px solid #35455d; padding: 4px; }
QTableView { gridline-color: #35455d; }
QMenuBar, QMenu, QStatusBar { background: #18273a; color: #e1e8f4; }
QMenuBar::item:selected, QMenu::item:selected { background: #285e76; }
QMenu::item:disabled { color: #78879b; }
QProgressBar { background: #18273a; color: #e1e8f4; border: 1px solid #425675; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #287b71; }
QSplitter::handle { background: #35455d; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width: 13px; background: #21354d; border-radius: 2px; }
QAbstractSpinBox { padding: 2px 1px; }
QAbstractSpinBox::up-arrow { image: url("@ASSETS@/up.svg"); width: 8px; height: 5px; }
QAbstractSpinBox::down-arrow, QComboBox::down-arrow { image: url("@ASSETS@/down.svg"); width: 8px; height: 5px; }
QComboBox::drop-down { width: 14px; border: none; }
QCheckBox::indicator { width: 12px; height: 12px; background: #18273a; border: 1px solid #62748c; border-radius: 2px; }
QCheckBox::indicator:checked { background: #20554f; border-color: #69dccb; image: url("@ASSETS@/check.svg"); }
QCheckBox::indicator:indeterminate { background: #20554f; image: url("@ASSETS@/minus.svg"); }
QCheckBox::indicator:disabled { border-color: #35455d; background: #202c3b; }
'''


def apply_theme(app):
    """Call before constructing widgets/figures, including dynamic device tabs."""
    app.setStyle('Fusion')
    font_dir = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for filename in ('malgun.ttf', 'segoeui.ttf', 'seguisym.ttf'):
        font_path = font_dir / filename
        if font_path.exists():
            QtGui.QFontDatabase.addApplicationFont(str(font_path))
    # Compact size retains the existing fixed-width RF editors and dense tables.
    app.setFont(QtGui.QFont('Malgun Gothic', 9))
    palette = QtGui.QPalette()
    roles = {
        'Window': BACKGROUND, 'WindowText': TEXT, 'Base': PANEL,
        'AlternateBase': '#1b2c40', 'Text': TEXT, 'Button': '#254b70',
        'ButtonText': TEXT, 'Highlight': '#285e76', 'HighlightedText': '#ffffff',
        'ToolTipBase': '#25415c', 'ToolTipText': TEXT, 'Link': ACCENT,
        'Light': '#425675', 'Midlight': '#35455d', 'Mid': '#35455d',
        'Dark': '#0b1220', 'Shadow': '#080d16', 'BrightText': ERROR,
    }
    for role, color in roles.items():
        palette.setColor(getattr(QtGui.QPalette, role), QtGui.QColor(color))
    for role in ('WindowText', 'Text', 'ButtonText'):
        palette.setColor(QtGui.QPalette.Disabled, getattr(QtGui.QPalette, role), QtGui.QColor('#78879b'))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET.replace('@ASSETS@', (Path(__file__).parent / 'theme_assets').as_posix()))

    # rcParams also cover axes reconstructed by clear()/subplot during refresh.
    import matplotlib as mpl
    from cycler import cycler
    mpl.rcParams.update({
        'figure.facecolor': BACKGROUND, 'figure.edgecolor': BACKGROUND,
        'axes.facecolor': '#131f30', 'axes.edgecolor': '#62748c',
        'axes.labelcolor': TEXT, 'text.color': TEXT,
        'xtick.color': MUTED, 'ytick.color': MUTED, 'grid.color': '#62748c',
        'legend.facecolor': '#18273a', 'legend.edgecolor': '#425675',
        'legend.labelcolor': TEXT, 'savefig.facecolor': BACKGROUND,
        'savefig.edgecolor': BACKGROUND, 'font.family': 'sans-serif',
        'font.sans-serif': ['Malgun Gothic', 'DejaVu Sans'],
        'axes.unicode_minus': False,  # Malgun Gothic lacks U+2212 on some Windows systems.
        'axes.prop_cycle': cycler(color=['#76baff', '#f3c46b', '#69dccb', '#ff8fa3', '#d6a2f3', '#8ddce8']),
    })

RF_INACTIVE_STYLE = "QPushButton {background-color:#3c4654; color:#b7c0cd;}"
