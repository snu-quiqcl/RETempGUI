"""Shared RF editor columns: name, readback, target, step, apply."""
from PyQt5 import QtWidgets

RF_COLUMN_WIDTHS = (150, 130, 160, 165, 110)


def align_rf_grid(grid):
    grid.setContentsMargins(9, 9, 9, 9)
    grid.setHorizontalSpacing(6)
    for column, width in enumerate(RF_COLUMN_WIDTHS):
        grid.setColumnMinimumWidth(column, width)
        grid.setColumnStretch(column, 0)
    grid.setColumnStretch(5, 1)
    for index in range(grid.count()):
        item = grid.itemAt(index)
        row, column, rows, columns = grid.getItemPosition(index)
        widget = item.widget()
        if widget is not None and columns == 1 and column < 5:
            widget.setFixedWidth(RF_COLUMN_WIDTHS[column])
            if isinstance(widget, QtWidgets.QLabel):
                widget.setWordWrap(True)


def value_with_unit(value, unit):
    """Keep the unit selector inside the shared target-value column."""
    container = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    value.setMinimumWidth(75)
    value.setMaximumWidth(16777215)
    unit.setFixedWidth(55)
    layout.addWidget(value, 1)
    layout.addWidget(unit)
    return container
