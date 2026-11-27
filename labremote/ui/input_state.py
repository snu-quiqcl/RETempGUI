"""Local form values only: restoration never emits instrument-control signals."""
import json
import logging
import math
import os
from pathlib import Path
from PyQt5 import QtCore, QtWidgets as W, sip
from labremote.configuration.paths import CONFIG_ROOT
from labremote.configuration.input_defaults import DEFAULT_INPUTS, load_input_defaults, resolve_default

LOG=logging.getLogger(__name__)
INPUTS=(W.QLineEdit,W.QAbstractSpinBox,W.QComboBox,W.QCheckBox,W.QRadioButton,W.QPlainTextEdit,W.QTextEdit,W.QSlider,W.QTableWidget,W.QAbstractButton,W.QGroupBox)


def value_of(widget):
    if sip.isdeleted(widget) or widget.property('persistInput') is False:return None
    if isinstance(widget,W.QTableWidget):
        from .persistence_models import table_value
        return table_value(widget)
    if isinstance(widget,(W.QAbstractButton,W.QGroupBox)):
        return {'kind':'check','value':widget.isChecked()} if widget.isCheckable() else None
    if isinstance(widget,W.QLineEdit):
        if widget.isReadOnly() or widget.echoMode()!=W.QLineEdit.Normal:return None
        if isinstance(widget.parentWidget(),(W.QAbstractSpinBox,W.QComboBox)):return None
        return {'kind':'text','value':widget.text()}
    if isinstance(widget,(W.QSpinBox,W.QDoubleSpinBox,W.QSlider)):
        if isinstance(widget,W.QAbstractSpinBox) and widget.isReadOnly():return None
        return {'kind':'number','value':widget.value()}
    if isinstance(widget,W.QComboBox):

        result={'kind':'choice','value':widget.route() if hasattr(widget,'route') else widget.currentText()}
        identity=widget.currentData()
        if isinstance(identity,(str,int,float,bool)):result['identity']=identity
        return result
    if isinstance(widget,(W.QCheckBox,W.QRadioButton)):
        return {'kind':'check','value':widget.isChecked()}
    if isinstance(widget,(W.QPlainTextEdit,W.QTextEdit)):
        if widget.isReadOnly():return None
        return {'kind':'multiline','value':widget.toPlainText()}
    return None


def apply_value(widget, saved):
    current=value_of(widget)
    if current is None:return True
    if not isinstance(saved,dict) or saved.get('kind')!=current['kind']:raise ValueError('Saved input type differs; original retained')
    value=saved.get('value');kind=saved['kind']
    blockers=[QtCore.QSignalBlocker(widget)]
    if isinstance(widget,(W.QPlainTextEdit,W.QTextEdit)):blockers.append(QtCore.QSignalBlocker(widget.document()))
    try:
        if kind=='table':
            from .persistence_models import restore_table
            restore_table(widget,saved)
        elif kind=='text' and isinstance(value,str):widget.setText(value)
        elif kind=='multiline' and isinstance(value,str):widget.setPlainText(value)
        elif kind=='number' and type(value) in (int,float) and math.isfinite(value):
            if not widget.minimum()<=value<=widget.maximum():raise ValueError('Saved value outside input limits; retained on disk')
            if not isinstance(widget,W.QDoubleSpinBox) and value!=int(value):raise ValueError('Integer input requires an integer')
            widget.setValue(value if isinstance(widget,W.QDoubleSpinBox) else int(value))
        elif kind=='check' and type(value) is bool:widget.setChecked(value)
        elif kind=='choice' and (isinstance(value,str) or value is None and hasattr(widget,'route')):
            if hasattr(widget,'route'):
                try:widget.setCurrentText(value);return True
                except ValueError:return False
            index=widget.findData(saved['identity']) if 'identity' in saved else widget.findText(value,QtCore.Qt.MatchExactly)
            if index>=0:widget.setCurrentIndex(index)
            elif widget.isEditable():widget.setEditText(value)
            elif value:return False  # Wait for discovery/port enumeration to populate the list.
        else:raise ValueError('Invalid saved value; original retained')
        return True
    finally:del blockers


class InputState(QtCore.QObject):
    def __init__(self,owner,path=None,defaults_path=None):
        super().__init__(owner);self.owner=owner
        self.path=Path(path) if path else CONFIG_ROOT/'ui/input_state.json'
        self.saved={};self.seen={};self.pending={};self.active=True;self._reported=set()
        self.store=None;self._generation=0;self._field_cache=None;self._cache_signature=None
        if path is None:
            from labremote.configuration.tab_state import TabStateStore
            self.store=TabStateStore(CONFIG_ROOT/'ui'/'tabs')
        self.models={};self.model_seen={};self.model_pending=set();self._restoring=False;self._invalid=False
        self._original=self.path.read_bytes() if self.path.exists() else None
        self.autosave=QtCore.QTimer(self);self.autosave.setInterval(1500)
        self.autosave.timeout.connect(self.checkpoint);self.autosave.start()
        self.defaults_path=Path(defaults_path) if defaults_path is not None else DEFAULT_INPUTS
        self.defaults=load_input_defaults(self.defaults_path,self.report)
        self.timer=QtCore.QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(150)
        self.timer.timeout.connect(self.restore)
        try:
            if self.path.exists():
                data=json.loads(self.path.read_text(encoding='utf-8-sig'))
                if data.get('schema_version')!=1 or not isinstance(data.get('inputs'),dict):raise ValueError('Invalid UI input state schema')
                self.saved=data['inputs'];self.models=data.get('models',{})
                if not isinstance(self.models,dict):raise ValueError('Invalid model state')
        except (OSError,ValueError,AttributeError) as error:
            self._invalid=True;self.report('Restore skipped; original file will not be overwritten: '+str(error))
        if self.store is not None:
            try:
                inputs,models=self.store.load();self.saved.update(inputs);self.models.update(models)
            except (OSError,ValueError,AttributeError) as error:
                self._invalid=True;self.report('Tab restore skipped; originals retained: '+str(error))
        W.QApplication.instance().installEventFilter(self)

    def report(self,text):
        if text in self._reported:return
        self._reported.add(text)
        LOG.warning('UI input state: %s',text)
        log=getattr(self.owner,'log',None)
        if log is not None:log.appendPlainText('UI input state: '+text)

    def roots(self,legacy=False):
        roots={}
        for family,panels in getattr(self.owner,'family_tabs',{}).items():
            for name,panel in panels.items():
                key='device/'+family+'/'+name;roots[key]=panel
                for attr in (('daily_tab','decay_tab','sequence_tab') if legacy else
                             ('daily_tab','decay_tab','sequence_tab','hom_tab','entanglement_tab','ion_check_tab','micromotion_tab')):
                    if hasattr(panel,attr):roots[key+'/'+attr]=getattr(panel,attr)
        for attr in ('experiment_workspace','ccd_tab','flip_tab','workflow_tab','queue_tab','monitor_tab','queue_monitor','connection_settings_window'):
            if hasattr(self.owner,attr):roots[attr]=getattr(self.owner,attr)
        if not legacy:
            workspace=getattr(self.owner,'experiment_workspace',None)
            if workspace is not None:
                for i,slot in enumerate(workspace.slots):
                    # A stable page identity is assigned at registration, independent of tab order.
                    for name,view in slot.views.items():roots['experiment/'+getattr(slot,'settings_id',str(i))+'/'+name]=view
            if hasattr(self.owner,'motor_tab'):roots['motor_tab']=self.owner.motor_tab
            for name,window in getattr(self.owner,'detail_windows',{}).items():
                if window not in roots.values():roots['window/'+name]=window
        if legacy:
            workspace=getattr(self.owner,'experiment_workspace',None)
            if workspace is not None:
                for i,slot in enumerate(workspace.slots):
                    for name,view in slot.views.items():roots['experiment/'+str(i)+'/'+name]=view
        roots['main']=self.owner
        return roots

    def fields(self,legacy=False):
        roots=self.roots(legacy=legacy)
        signature=(self._generation,tuple((k,id(v)) for k,v in roots.items()))
        if not legacy and self._cache_signature==signature and self._field_cache is not None:
            if not any(sip.isdeleted(v) for v in (*self._field_cache.values(),*self.model_widgets.values())):
                return self._field_cache
        root_ids={id(v) for v in roots.values()};result={};used=set()
        self.model_widgets={} if not legacy else getattr(self,'model_widgets',{})
        source_ids={id(getattr(w,'source',None)) for w in W.QApplication.allWidgets()} if not legacy else set()
        # Prefer stable Python attribute / dictionary keys (instrument, chamber, axis).
        for root_key,root in roots.items():
            if sip.isdeleted(root):continue
            visited=set()
            def walk(value,key,depth=0):
                if depth>12:return
                if isinstance(value,W.QWidget) or (not legacy and value is root and isinstance(value,QtCore.QObject)):
                    # Closed/replaced views can leave Python aliases behind;
                    # check the Qt object's lifetime before any Qt call.
                    if sip.isdeleted(value):return
                    if id(value) in visited or (value is not root and id(value) in root_ids):return
                    visited.add(id(value))
                    widget_root=root if isinstance(root,W.QWidget) else getattr(root,'tab',None)
                    if value is not root and not (widget_root is not None and not sip.isdeleted(widget_root) and widget_root.isAncestorOf(value) or getattr(value,'owner',None) is self.owner):return
                    if not legacy:
                        from .persistence_models import supported
                        if supported(value):self.model_widgets[key]=value
                    if isinstance(value,INPUTS):
                        # Python source documents retain their existing save/close workflow.
                        if id(value) in source_ids or (key.endswith('/source') and type(value).__module__.startswith('PyQt5')):return
                        if id(value) not in used and value_of(value) is not None:
                            used.add(id(value));result[key]=value
                        if not isinstance(value,W.QGroupBox):return
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
                if id(widget) in used or id(widget) in source_ids or not isinstance(widget,INPUTS) or value_of(widget) is None:continue
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
        if not legacy:
            self.legacy_keys={id(widget):key for key,widget in self.fields(legacy=True).items()}
            from labremote.configuration.legacy_inputs import experiment_prefix
            aliases=[]
            workspace=getattr(self.owner,'experiment_workspace',None)
            if workspace is not None:
                for slot in workspace.slots:
                    for name,view in slot.views.items():
                        old=experiment_prefix(view,name)
                        if old:aliases.append(('experiment/'+slot.settings_id+'/'+name,old))
            self.older_keys={key:old+key[len(prefix):] for key in result for prefix,old in aliases if key.startswith(prefix+'/')}
            self._field_cache=result;self._cache_signature=signature
        return result

    def schedule(self,*_):
        if self.active and not self.timer.isActive():self.timer.start()

    def eventFilter(self,watched,event):
        if self.active and isinstance(watched,W.QWidget) and event.type() in (QtCore.QEvent.ChildAdded,QtCore.QEvent.ChildRemoved,QtCore.QEvent.Polish):
            window=watched.window()
            if window is self.owner or getattr(window,'owner',None) is self.owner:
                if event.type()!=QtCore.QEvent.Polish:self._generation+=1
                self.schedule()
        return False

    def restore(self):
        if not self.active or self._restoring:return
        self._restoring=True
        try:self._restore()
        finally:self._restoring=False

    def _restore(self):
        fields=self.fields()
        # Restore structured models before their individual view controls.
        from .persistence_models import restore as restore_model
        for key,widget in tuple(self.model_widgets.items()):
            if self.model_seen.get(key) is widget:continue
            self.model_seen[key]=widget
            if key in self.models:
                try:restore_model(widget,self.models[key])
                except Exception as exc:self.model_pending.add(key);self.report(key+': '+str(exc))
        # Model restoration can replace controls collected by the first pass.
        # Recollect before constructing blockers or wiring signals to them.
        fields=self.fields()
        blockers=[QtCore.QSignalBlocker(widget) for widget in fields.values()]
        for key,widget in fields.items():
            if self.seen.get(key) is widget and key not in self.pending:continue
            fresh=self.seen.get(key) is not widget;self.seen[key]=widget
            if fresh:
                signal=getattr(widget,'editingFinished',None) or getattr(widget,'sliderReleased',None)
                if signal is not None:signal.connect(lambda k=key:self.pending.pop(k,None))
            if fresh and isinstance(widget,W.QComboBox):
                widget.model().rowsInserted.connect(self.schedule)
                widget.model().modelReset.connect(self.schedule)
                widget.activated.connect(lambda _,k=key:self.pending.pop(k,None))
            candidates=(key,self.legacy_keys.get(id(widget)),self.older_keys.get(key))
            saved_key=next((k for k in candidates if k in self.saved),key)
            selected=self.saved.get(saved_key)
            from_default=saved_key not in self.saved
            if from_default:selected=resolve_default(self.defaults,key)
            if selected is not None:
                try:
                    if from_default:
                        current=value_of(widget)
                        if selected['kind']!=current['kind']:
                            raise ValueError('Configured default kind differs from this input')
                        if selected['kind']=='number':
                            if not widget.minimum()<=selected['value']<=widget.maximum():
                                raise ValueError('Configured default is outside the allowed input range')
                            if not isinstance(widget,W.QDoubleSpinBox) and selected['value']!=int(selected['value']):
                                raise ValueError('Integer input requires an integer default')
                    if apply_value(widget,selected):self.pending.pop(key,None)
                    else:self.pending[key]=widget
                except (TypeError,ValueError,RuntimeError) as error:self.report(key+': '+str(error));self.pending[key]=widget
        del blockers
        from .mapping_persistence import restore_legacy
        restore_legacy(self)

    def checkpoint(self):
        if not self.active or self._restoring or getattr(self.owner,'_closing',False):return
        self.restore()
        self.save()

    def save(self):
        if self._invalid:return False
        try:
            current=self.path.read_bytes() if self.path.exists() else None
            if current!=self._original:
                self.report('Settings changed outside this window; reload before saving. Original retained.');return False
            from .mapping_persistence import persist,views
            for prefix,view in views(self.roots()):
                try:persist(view)
                except (OSError,ValueError,TypeError,KeyError) as exc:self.report(prefix+': 매핑 저장 보류: '+str(exc))
            values=dict(self.saved)
            for key,widget in self.fields().items():
                value=value_of(widget)
                if key not in self.pending and value is not None:values[key]=value
            from .persistence_models import capture
            models=dict(self.models)
            for key,widget in self.model_widgets.items():
                if key not in self.model_pending:models[key]=capture(widget)
            if self.store is not None:
                self.store.save(values,models,self.roots())
                self.saved=values;self.models=models
                return True
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.path.with_name(self.path.name+'.tmp')
            original_doc=json.loads(self._original.decode('utf-8-sig')) if self._original else {}
            original_doc.update(schema_version=1,inputs=values,models=models)
            payload=(json.dumps(original_doc,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
            if payload!=current:
                temporary.write_bytes(payload);os.replace(temporary,self.path)
            self._original=payload;self.saved=values;self.models=models
            return True
        except (OSError,ValueError,TypeError) as error:
            self.report('Save failed: '+str(error));return False

    def stop(self):
        self.active=False;self.timer.stop();self.autosave.stop();W.QApplication.instance().removeEventFilter(self)
