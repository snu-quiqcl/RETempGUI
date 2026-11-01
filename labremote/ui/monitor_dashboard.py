"""Read-only mirrors of existing displays. Never acquire or command hardware."""
import json
from pathlib import Path
from PyQt5 import QtCore, QtGui, QtWidgets
from labremote.config.paths import CONFIG_ROOT

PUBLIC = CONFIG_ROOT/'ui/monitor.json'
LOCAL = CONFIG_ROOT/'ui/monitor.local.json'
FAMILIES = ('ds1052e', 'mso7054', 'osa', 'thermotek', 'mdt')


def validate(config):
    if not isinstance(config,dict):raise ValueError('Monitor config must be an object')
    if type(config.get('columns')) is not int or not 1<=config['columns']<=3:raise ValueError('Monitor columns: 1..3')
    selected=config.get('selected')
    if selected is not None and (not isinstance(selected,list) or any(not isinstance(s,str) for s in selected)):
        raise ValueError('Monitor selected must be null or a list of source IDs')
    return config


def load_config():
    config=json.loads(PUBLIC.read_text(encoding='utf-8-sig'))
    if LOCAL.exists():config.update(json.loads(LOCAL.read_text(encoding='utf-8-sig')))
    return validate(config)


def sources(families):
    for family in FAMILIES:
        for name,panel in families.get(family,{}).items():
            yield family+'/'+name, family.upper()+' · '+name,panel
            if family=='mdt' and hasattr(panel,'pid_tab'):
                yield 'pid/'+name,'PID · '+name,panel.pid_tab


def readout_labels(panel):
    """Return original label widgets, keeping their formatting and units."""
    rows=[]
    for attr in ('status','message','repeat_status','values','time_read'):
        label=getattr(panel,attr,None)
        if isinstance(label,QtWidgets.QLabel):rows.append(('',label))
    for key,label in getattr(panel,'labels',{}).items():
        title=key
        # Locate the caption next to the original readback, including its unit.
        for layout in panel.findChildren(QtWidgets.QGridLayout):
            index=layout.indexOf(label)
            if index>=0:
                row,col,_,_=layout.getItemPosition(index)
                caption=layout.itemAtPosition(row,0)
                if caption and isinstance(caption.widget(),QtWidgets.QLabel):title=caption.widget().text()
                break
        rows.append((title,label))
    for attr in ('vert_read','freq_read','vpp_read','extra_measurements'):
        for key,label in getattr(panel,attr,{}).items():
            title=key
            if attr=='freq_read':title+=' '+panel.first_measurement_title
            elif attr=='vpp_read':title+=' Vpp'
            rows.append((title,label))
    return rows


class PlotMirror(QtWidgets.QWidget):
    def __init__(self,canvas,parent=None):
        super().__init__(parent);self.canvas=canvas;self.frame=None;self.dirty=True
        self.setMinimumHeight(160)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Expanding)
        self.cid=canvas.mpl_connect('draw_event',self.source_drawn)
        self.destroyed.connect(lambda:canvas.mpl_disconnect(self.cid))

    def source_drawn(self,event):
        # Only copy pixels once per dashboard refresh, regardless of acquisition rate.
        self.dirty=True

    def refresh(self):
        if not self.dirty:return
        # Hidden detail windows still render their normal draw_idle updates.
        if not hasattr(self.canvas,'renderer'):self.canvas.draw()
        renderer=self.canvas.renderer
        width,height=int(renderer.width),int(renderer.height)
        self.frame=QtGui.QImage(renderer.buffer_rgba(),width,height,4*width,QtGui.QImage.Format_RGBA8888).copy()
        self.dirty=False;self.update()

    def paintEvent(self,event):
        painter=QtGui.QPainter(self);painter.fillRect(self.rect(),self.palette().window())
        if self.frame is not None:
            size=self.frame.size().scaled(self.size(),QtCore.Qt.KeepAspectRatio)
            rect=QtCore.QRect(QtCore.QPoint((self.width()-size.width())//2,(self.height()-size.height())//2),size)
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            painter.drawImage(rect,self.frame)


class MonitorCard(QtWidgets.QGroupBox):
    def __init__(self,title,panel,parent=None):
        super().__init__(title,parent);self.source=panel;self.setMinimumWidth(260);self.setFixedHeight(370)
        root=QtWidgets.QVBoxLayout(self);self.plot=None
        if hasattr(panel,'canvas'):
            self.plot=PlotMirror(panel.canvas,self);root.addWidget(self.plot,1)
        area=QtWidgets.QScrollArea();area.setWidgetResizable(True)
        content=QtWidgets.QWidget();form=QtWidgets.QFormLayout(content);self.rows=[]
        for title,source in readout_labels(panel):
            target=QtWidgets.QLabel();target.setWordWrap(True);target.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            if title:form.addRow(title,target)
            else:form.addRow(target)
            self.rows.append((source,target))
        area.setWidget(content)
        if self.plot:area.setMaximumHeight(125)
        root.addWidget(area)

    def refresh(self):
        for source,target in self.rows:
            if target.text()!=source.text():target.setText(source.text())
            target.setToolTip(source.toolTip());target.setStyleSheet(source.styleSheet())
        if self.plot:self.plot.refresh()


class MonitorDashboard(QtWidgets.QWidget):
    def __init__(self,provider,parent=None):
        super().__init__(parent);self.provider=provider;self.cards={};self.checks={};self._layout_signature=None
        error=''
        try:self.config=load_config()
        except Exception as exc:self.config={'columns':3,'selected':[]};error=str(exc)
        root=QtWidgets.QVBoxLayout(self)
        row=QtWidgets.QHBoxLayout();root.addLayout(row)
        toggle=QtWidgets.QCheckBox('표시 장비 선택');toggle.setChecked(True);row.addWidget(toggle)
        row.addWidget(QtWidgets.QLabel('열 수'));self.columns=QtWidgets.QSpinBox();self.columns.setRange(1,3);self.columns.setValue(self.config['columns']);row.addWidget(self.columns)
        reload_button=QtWidgets.QPushButton('설정 다시 읽기');row.addWidget(reload_button);row.addStretch()
        self.options=QtWidgets.QScrollArea();self.options.setWidgetResizable(True);self.options.setMaximumHeight(110)
        self.option_content=QtWidgets.QWidget();self.option_grid=QtWidgets.QGridLayout(self.option_content);self.options.setWidget(self.option_content);root.addWidget(self.options)
        toggle.toggled.connect(self.options.setVisible)
        self.message=QtWidgets.QLabel(error or '상세 UI의 표시를 그대로 공유합니다. 측정 시작·설정은 각 장비 창에서 합니다.');self.message.setWordWrap(True);root.addWidget(self.message)
        self.scroll=QtWidgets.QScrollArea();self.scroll.setWidgetResizable(True)
        self.content=QtWidgets.QWidget();self.grid=QtWidgets.QGridLayout(self.content);self.grid.setAlignment(QtCore.Qt.AlignTop);self.scroll.setWidget(self.content);root.addWidget(self.scroll,1)
        self.columns.valueChanged.connect(self.selection_changed);reload_button.clicked.connect(self.reload_config)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(500);self.timer.timeout.connect(self.refresh)

    def showEvent(self,event):
        super().showEvent(event);self.refresh();self.timer.start()

    def hideEvent(self,event):
        self.timer.stop();super().hideEvent(event)

    def selection_changed(self,*args):
        # Preserve choices for temporarily absent devices.
        selected=set(self.config['selected'] or [])-set(self.checks)
        selected.update(key for key,box in self.checks.items() if box.isChecked())
        self.config={'columns':self.columns.value(),'selected':sorted(selected)}
        try:
            LOCAL.parent.mkdir(parents=True,exist_ok=True)
            temp=LOCAL.with_suffix('.tmp');temp.write_text(json.dumps(self.config,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');temp.replace(LOCAL)
            self.message.setText('표시 설정 저장됨 · '+str(LOCAL))
        except Exception as exc:self.message.setText('표시 설정 저장 실패: '+str(exc))
        self.relayout()

    def reload_config(self):
        try:config=load_config()
        except Exception as exc:self.message.setText('표시 설정 읽기 실패: '+str(exc));return
        self.config=config
        blocker=QtCore.QSignalBlocker(self.columns);self.columns.setValue(config['columns']);del blocker
        for key,box in self.checks.items():
            blocker=QtCore.QSignalBlocker(box);box.setChecked(config['selected'] is None or key in config['selected']);del blocker
        self.relayout();self.message.setText('표시 설정을 다시 읽었습니다.');self.refresh()

    def refresh(self):
        if not self.isVisible():return
        current=dict((key,(title,panel)) for key,title,panel in sources(self.provider()))
        for key in list(self.cards):
            if key not in current or self.cards[key].source is not current[key][1]:
                card=self.cards.pop(key);self.grid.removeWidget(card);card.hide();card.deleteLater()
                box=self.checks.pop(key);self.option_grid.removeWidget(box);box.deleteLater();self._layout_signature=None
        for key,(title,panel) in current.items():
            if key in self.cards:continue
            self.cards[key]=MonitorCard(title,panel,self.content)
            box=QtWidgets.QCheckBox(title);box.setToolTip(key)
            box.setChecked(self.config['selected'] is None or key in self.config['selected'])
            box.toggled.connect(self.selection_changed);self.checks[key]=box;self._layout_signature=None
        self.relayout()
        for key,card in self.cards.items():
            if self.checks[key].isChecked():card.refresh()

    def relayout(self):
        selected=tuple(key for key,box in self.checks.items() if box.isChecked())
        signature=(tuple(self.cards),selected,self.columns.value())
        if signature==self._layout_signature:return
        self._layout_signature=signature
        for index,box in enumerate(self.checks.values()):self.option_grid.addWidget(box,index//3,index%3)
        for card in self.cards.values():self.grid.removeWidget(card);card.hide()
        columns=self.columns.value()
        for col in range(3):self.grid.setColumnStretch(col,1 if col<columns else 0)
        for index,key in enumerate(selected):
            card=self.cards[key];self.grid.addWidget(card,index//columns,index%columns);card.show()
