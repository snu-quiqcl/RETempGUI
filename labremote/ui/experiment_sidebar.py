"""Hide an experiment's whole settings column without changing its inputs."""
from PyQt5 import QtCore, QtWidgets


class SettingsPanelToggle(QtWidgets.QToolButton):
    def __init__(self,splitter,settings_scroll,parent=None):
        super().__init__(parent)
        self.splitter=splitter;self.settings_scroll=settings_scroll
        self.expanded_width=max(390,settings_scroll.minimumWidth())
        self.setCheckable(True)
        self.setFixedSize(28,28)
        self.setProperty('persistInput',False)
        self.toggled.connect(self.set_expanded)
        self.set_expanded(False)

    def set_expanded(self,expanded):
        if expanded:
            self.settings_scroll.show()
            available=max(1,self.splitter.width()-self.splitter.handleWidth())
            self.splitter.setSizes([self.expanded_width,max(1,available-self.expanded_width)])
        else:
            sizes=self.splitter.sizes()
            if not self.settings_scroll.isHidden() and sizes and sizes[0]>0:
                self.expanded_width=max(self.settings_scroll.minimumWidth(),sizes[0])
            self.settings_scroll.hide()
        self.setArrowType(QtCore.Qt.LeftArrow if expanded else QtCore.Qt.RightArrow)
        label='설정 패널 전체 접기' if expanded else '설정 패널 펼치기'
        self.setToolTip(label);self.setAccessibleName(label)


def install_settings_toggle(splitter,settings_scroll):
    """Keep the reveal button beside results, visible even when settings hide."""
    result=splitter.widget(1)
    container=QtWidgets.QWidget()
    splitter.replaceWidget(1,container)
    layout=QtWidgets.QHBoxLayout(container);layout.setContentsMargins(0,0,0,0);layout.setSpacing(2)
    toggle=SettingsPanelToggle(splitter,settings_scroll,container)
    layout.addWidget(toggle,0,QtCore.Qt.AlignTop)
    layout.addWidget(result,1)
    result.show();container.show()
    splitter.setChildrenCollapsible(False)
    splitter.setStretchFactor(0,0);splitter.setStretchFactor(1,1)
    return toggle
