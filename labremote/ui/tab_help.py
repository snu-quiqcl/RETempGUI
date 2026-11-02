"""Configuration-backed hover help, including dynamically discovered tabs."""
import json
import logging
from pathlib import Path
from PyQt5 import QtCore, QtWidgets
from labremote.config.paths import CONFIG_ROOT

class TabHelp(QtCore.QObject):
    def __init__(self, owner, config_root=None):
        super().__init__(owner)
        self.owner=owner
        self.root=Path(config_root) if config_root else CONFIG_ROOT/'ui'
        self.signature=None;self.mapping={};self.error=None

    def reload(self):
        paths=[self.root/'tab_descriptions.json',self.root/'tab_descriptions.local.json']
        try:
            signature=tuple((p.stat().st_mtime_ns,p.stat().st_size) if p.exists() else None for p in paths)
            if signature==self.signature:return
            merged={}
            for path in paths:
                if not path.exists():continue
                obj=json.loads(path.read_text(encoding='utf-8-sig'))
                if not isinstance(obj,dict) or set(obj)!={'descriptions'} or not isinstance(obj['descriptions'],dict):
                    raise ValueError(f'{path.name}: expected descriptions object')
                for key,value in obj['descriptions'].items():
                    if not isinstance(key,str) or not isinstance(value,str):raise ValueError('Tab descriptions must be strings')
                    merged[key.casefold()]=value
            self.mapping=merged;self.signature=signature;self.error=None
        except (OSError,ValueError) as exc:
            if str(exc)!=self.error:logging.getLogger(__name__).warning('Tab help config: %s',exc)
            self.error=str(exc)  # Keep the last valid configuration; never interrupt control.

    def description(self, label, parent_label=None):
        self.reload()
        if parent_label:
            key=(parent_label+'/'+label).casefold()
            if key in self.mapping:return self.mapping[key]
        return self.mapping.get(label.casefold())

    def eventFilter(self, watched, event):
        if event.type()!=QtCore.QEvent.ToolTip or not isinstance(watched,QtWidgets.QTabBar):return False
        window=watched.window()
        if window is not self.owner and getattr(window,'owner',None) is not self.owner:return False
        index=watched.tabAt(event.pos())
        if index<0:return False
        parent_label=None
        tabs=watched.parentWidget()
        ancestor=tabs.parentWidget() if tabs else None
        while ancestor is not None:
            if isinstance(ancestor,QtWidgets.QTabWidget):
                for i in range(ancestor.count()):
                    page=ancestor.widget(i)
                    if page is tabs or page.isAncestorOf(tabs):
                        parent_label=ancestor.tabText(i);break
                if parent_label is not None:break
            ancestor=ancestor.parentWidget()
        text=self.description(watched.tabText(index),parent_label)
        if text is None:return False  # Retain existing tooltips when not configured.
        if text:
            from html import escape
            QtWidgets.QToolTip.showText(event.globalPos(),'<qt>'+escape(text).replace('\n','<br>')+'</qt>',watched,watched.tabRect(index))
        else:QtWidgets.QToolTip.hideText()
        event.accept();return True
