"""Presentation-only layouts; pages retain their public identity and signals."""
from PyQt5 import QtCore, QtWidgets as W


class PageScroll(W.QScrollArea):
    def __init__(self, page):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(W.QFrame.NoFrame)
        self.setWidget(page)

    def minimumSizeHint(self):
        return QtCore.QSize(0, 0)

    def sizeHint(self):
        return QtCore.QSize(640, 480)


class ScrollTabs(W.QTabWidget):
    """Each page scrolls independently, without changing callers' page objects."""
    def addTab(self, page, *args):
        return self.insertTab(self.count(), page, *args)

    def insertTab(self, index, page, *args):
        old = self.indexOf(page)
        if old >= 0:
            self.removeTab(old)
        return super().insertTab(index, PageScroll(page), *args)

    def widget(self, index):
        wrapper = super().widget(index)
        return wrapper.widget() if isinstance(wrapper, PageScroll) else wrapper

    def currentWidget(self):
        return self.widget(self.currentIndex())

    def indexOf(self, page):
        for index in range(self.count()):
            if self.widget(index) is page:
                return index
        return -1

    def setCurrentWidget(self, page):
        index = self.indexOf(page)
        if index >= 0:
            self.setCurrentIndex(index)

    def removeTab(self, index):
        wrapper = super().widget(index)
        if wrapper is None:
            return
        # Like QTabWidget.removeTab, removal must not delete the user's page.
        # Detach after removal so currentChanged observers see a consistent list.
        super().removeTab(index)
        if isinstance(wrapper, PageScroll):
            page = wrapper.takeWidget()
            if page is not None:
                page.hide()
                page.setParent(self)
            wrapper.deleteLater()

    def clear(self):
        while self.count():
            self.removeTab(self.count() - 1)


class FlowLayout(W.QLayout):
    """Wrap action buttons instead of stretching a single horizontal row."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(6)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return QtCore.Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QtCore.QRect(0, 0, width, 0), True)

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self.items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QtCore.QSize(left + right, top + bottom)

    def sizeHint(self):
        return self.minimumSize()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, False)

    def arrange(self, rect, measure):
        left, top, right, bottom = self.getContentsMargins()
        area = rect.adjusted(left, top, -right, -bottom)
        x, y, height = area.x(), area.y(), 0
        for item in self.items:
            if item.isEmpty():
                continue
            size = item.sizeHint()
            if height and x + size.width() > area.right() + 1:
                x = area.x()
                y += height + self.spacing()
                height = 0
            if not measure:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), size))
            x += size.width() + self.spacing()
            height = max(height, size.height())
        return y + height - rect.y() + bottom


def bounded_combo(combo):
    combo.setMinimumContentsLength(14)
    combo.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon)
    # The popup keeps the full names; the closed control need not fit every item.
    combo.currentTextChanged.connect(combo.setToolTip)

