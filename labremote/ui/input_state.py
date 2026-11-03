"""Local form values only: restoration never emits instrument-control signals."""
import json
import logging
import math
import os
from pathlib import Path
from PyQt5 import QtCore, QtWidgets as W
from labremote.config.paths import CONFIG_ROOT

LOG=logging.getLogger(__name__)
INPUTS=(W.QLineEdit,W.QAbstractSpinBox,W.QComboBox,W.QCheckBox,W.QRadioButton,W.QPlainTextEdit,W.QTextEdit,W.QSlider)


def value_of(widget):
    if widget.property('persistInput') is False:return None
    if isinstance(widget,W.QLineEdit):
        if widget.isReadOnly() or widget.echoMode()!=W.QLineEdit.Normal:return None
        if isinstance(widget.parentWidget(),(W.QAbstractSpinBox,W.QComboBox)):return None
        return {'kind':'text','value':widget.text()}
    if isinstance(widget,(W.QSpinBox,W.QDoubleSpinBox,W.QSlider)):
        if isinstance(widget,W.QAbstractSpinBox) and widget.isReadOnly():return None
        return {'kind':'number','value':widget.value()}
    if isinstance(widget,W.QComboBox):
        return {'kind':'choice','value':widget.currentText()}
    if isinstance(widget,(W.QCheckBox,W.QRadioButton)):
        return {'kind':'check','value':widget.isChecked()}
    if isinstance(widget,(W.QPlainTextEdit,W.QTextEdit)):
        if widget.isReadOnly():return None
        return {'kind':'multiline','value':widget.toPlainText()}
    return None


def apply_value(widget, saved):
    current=value_of(widget)
    if current is None or not isinstance(saved,dict) or saved.get('kind')!=current['kind']:return True
    value=saved.get('value');kind=saved['kind']
    blockers=[QtCore.QSignalBlocker(widget)]
    if isinstance(widget,(W.QPlainTextEdit,W.QTextEdit)):blockers.append(QtCore.QSignalBlocker(widget.document()))
    try:
        if kind=='text' and isinstance(value,str):widget.setText(value)
        elif kind=='multiline' and isinstance(value,str):widget.setPlainText(value)
        elif kind=='number' and type(value) in (int,float) and math.isfinite(value):
            widget.setValue(value if isinstance(widget,W.QDoubleSpinBox) else int(value))
        elif kind=='check' and type(value) is bool:widget.setChecked(value)
        elif kind=='choice' and isinstance(value,str):
            index=widget.findText(value,QtCore.Qt.MatchExactly)
            if index>=0:widget.setCurrentIndex(index)
            elif widget.isEditable():widget.setEditText(value)
            elif value:return False  # Wait for discovery/port enumeration to populate the list.
        return True
    finally:del blockers


class InputState(QtCore.QObject):
    def __init__(self,owner,path=None):
        super().__init__(owner);self.owner=owner
        self.path=Path(path) if path else CONFIG_ROOT/'ui/input_state.local.json'
        self.saved={};self.seen={};self.pending={};self.active=True
        self.timer=QtCore.QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(150)
        self.timer.timeout.connect(self.restore)
        try:
            if self.path.exists():
                data=json.loads(self.path.read_text(encoding='utf-8-sig'))
                if data.get('schema_version')!=1 or not isinstance(data.get('inputs'),dict):raise ValueError('Invalid UI input state schema')
                self.saved=data['inputs']
        except (OSError,ValueError,AttributeError) as error:self.report('Restore skipped: '+str(error))
        W.QApplication.instance().installEventFilter(self)

    def report(self,text):
        LOG.warning('UI input state: %s',text)
        log=getattr(self.owner,'log',None)
        if log is not None:log.appendPlainText('UI input state: '+text)

    def roots(self):
        roots={}
        for family,panels in getattr(self.owner,'family_tabs',{}).items():
            for name,panel in panels.items():
                key='device/'+family+'/'+name;roots[key]=panel
                for attr in ('daily_tab','decay_tab','sequence_tab'):
                    if hasattr(panel,attr):roots[key+'/'+attr]=getattr(panel,attr)
        for attr in ('ccd_tab','flip_tab','workflow_tab','queue_tab','monitor_tab','queue_monitor','connection_settings_window'):
            if hasattr(self.owner,attr):roots[attr]=getattr(self.owner,attr)
        roots['main']=self.owner
        return roots

    def fields(self):
        roots=self.roots();root_ids={id(v) for v in roots.values()};result={};used=set()
        # Prefer stable Python attribute / dictionary keys (instrument, chamber, axis).
        for root_key,root in roots.items():
            visited=set()
            def walk(value,key,depth=0):
                if depth>12:return
                if isinstance(value,W.QWidget):
                    if id(value) in visited or (value is not root and id(value) in root_ids):return
                    visited.add(id(value))
                    if value is not root and not (root.isAncestorOf(value) or getattr(value,'owner',None) is self.owner):return
                    if isinstance(value,INPUTS):
                        # Python source documents retain their existing save/close workflow.
                        if key.endswith('/source') and type(value).__module__.startswith('PyQt5'):return
                        if id(value) not in used and value_of(value) is not None:
                            used.add(id(value));result[key]=value
                        return
                    for attr,child in sorted(vars(value).items()):
                        if not attr.startswith('_') and attr not in ('owner','parent','input_state'):
                            walk(child,key+'/'+attr,depth+1)
                elif isinstance(value,dict):
                    for name,child in sorted(value.items(),key=lambda pair:repr(pair[0])):
                        if isinstance(child,(W.QWidget,dict,list,tuple)):walk(child,key+'/'+str(name),depth+1)
                elif isinstance(value,(list,tuple)):
                    for i,child in enumerate(value):
                        if isinstance(child,(W.QWidget,dict,list,tuple)):walk(child,key+'/'+str(i),depth+1)
            walk(root,root_key)
            # Cover locally-created fields which have no Python attribute.
            for widget in root.findChildren(W.QWidget):
                if id(widget) in used or not isinstance(widget,INPUTS) or value_of(widget) is None:continue
                parent=widget;parts=[];owned=True
                while parent is not root:
                    if parent is None or (parent is not widget and id(parent) in root_ids):owned=False;break
                    if parent is getattr(root,'source',None):owned=False;break
                    p=parent.parentWidget()
                    if p is None:owned=False;break
                    siblings=[w for w in p.findChildren(W.QWidget,options=QtCore.Qt.FindDirectChildrenOnly) if type(w) is type(parent)]
                    parts.append(parent.objectName() or type(parent).__name__+'['+str(siblings.index(parent))+']')
                    parent=p
                if owned:
                    used.add(id(widget));result[root_key+'/qt/'+'/'.join(reversed(parts))]=widget
        return result

    def schedule(self,*_):
        if self.active and not self.timer.isActive():self.timer.start()

    def eventFilter(self,watched,event):
        if self.active and isinstance(watched,W.QWidget) and event.type() in (QtCore.QEvent.ChildAdded,QtCore.QEvent.Polish):
            window=watched.window()
            if window is self.owner or getattr(window,'owner',None) is self.owner:self.schedule()
        return False

    def restore(self):
        if not self.active:return
        fields=self.fields()
        blockers=[QtCore.QSignalBlocker(widget) for widget in fields.values()]
        for key,widget in fields.items():
            if self.seen.get(key) is widget and key not in self.pending:continue
            fresh=self.seen.get(key) is not widget;self.seen[key]=widget
            if fresh and isinstance(widget,W.QComboBox):
                widget.model().rowsInserted.connect(self.schedule)
                widget.model().modelReset.connect(self.schedule)
                widget.activated.connect(lambda _,k=key:self.pending.pop(k,None))
            if key in self.saved:
                try:
                    if apply_value(widget,self.saved[key]):self.pending.pop(key,None)
                    else:self.pending[key]=widget
                except (TypeError,ValueError,RuntimeError) as error:self.report(key+': '+str(error));self.pending.pop(key,None)
        del blockers

    def save(self):
        try:
            values=dict(self.saved)
            for key,widget in self.fields().items():
                if key not in self.pending:values[key]=value_of(widget)
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.path.with_name(self.path.name+'.tmp')
            temporary.write_text(json.dumps({'schema_version':1,'inputs':values},ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            os.replace(temporary,self.path);self.saved=values
            return True
        except (OSError,ValueError,TypeError) as error:
            self.report('Save failed: '+str(error));return False

    def stop(self):
        self.active=False;self.timer.stop();W.QApplication.instance().removeEventFilter(self)
