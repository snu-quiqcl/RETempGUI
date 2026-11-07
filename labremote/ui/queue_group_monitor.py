"""Group/workflow dashboard fed only by Queue manifests and saved result files."""
from copy import deepcopy
import json
import numpy as np
from PyQt5 import QtCore,QtWidgets
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from labremote.runtime.queue_monitor_data import ResultStore,group_key,pool_spam,pool_ent,settings_key


class SnapshotReader(QtCore.QThread):
    loaded=QtCore.pyqtSignal(object)
    failed=QtCore.pyqtSignal(str)
    def __init__(self,store,state,parent=None):super().__init__(parent);self.store=store;self.state=state
    def run(self):
        try:self.loaded.emit(self.store.snapshot(self.state))
        except Exception as exc:self.failed.emit(str(exc))


def chart(parent,height):
    figure=Figure(figsize=(7,3));canvas=FigureCanvasQTAgg(figure);canvas.setMinimumHeight(height)
    canvas.setMaximumHeight(height+10)
    parent.addWidget(canvas);return figure,canvas


class WorkflowPanel(QtWidgets.QGroupBox):
    def __init__(self,slot,parent=None):
        super().__init__(parent);self.kind=slot['kind'];self.slot=slot;self.dialogs=[];self.signature=None
        self.setTitle(slot['name']);self.layout_=QtWidgets.QVBoxLayout(self)
        self.summary=QtWidgets.QLabel();self.summary.setWordWrap(True);self.layout_.addWidget(self.summary)
        self.mode=QtWidgets.QComboBox();self.cycle=QtWidgets.QComboBox()
        if self.kind=='ent':
            row=QtWidgets.QHBoxLayout();self.layout_.addLayout(row)
            self.mode.addItems(['그룹 누적','최신 회차','회차 선택']);row.addWidget(self.mode);row.addWidget(self.cycle)
            full=QtWidgets.QPushButton('기존 탭 전체 그래프');full.clicked.connect(self.open_full);row.addWidget(full);row.addStretch()
            self.mode.currentIndexChanged.connect(self.draw);self.cycle.currentIndexChanged.connect(self.draw)
            self.figure,self.canvas=chart(self.layout_,320)
            self.note=QtWidgets.QLabel('로그 기하분포의 x축은 시간(초)이 아닌 herald까지의 시도 횟수입니다.');self.note.setWordWrap(True);self.layout_.addWidget(self.note)
        elif self.kind in ('ion','spam'):self.figure,self.canvas=chart(self.layout_,230)
        else:
            self.summary.setText('전용 그래프가 없는 workflow입니다. 아래 회차별 결과와 실행 목록에서 상태·metrics를 확인하세요.')
        self.update_slot(slot)

    def update_slot(self,slot):
        self.slot=slot
        self.setTitle(slot['name']+(' · 설정 '+slot['profile'][:6] if slot.get('variant') else ''))
        self.setToolTip(json.dumps(slot['records'][0]['settings'],ensure_ascii=False,indent=2) if slot['records'] else '')
        # Do not redraw plots for unrelated Queue transitions.
        signature=json.dumps(slot,sort_keys=True,ensure_ascii=False)
        if signature==self.signature:return
        self.signature=signature
        if self.kind=='ent':
            selected=self.cycle.currentData()
            with QtCore.QSignalBlocker(self.cycle):
                self.cycle.clear()
                for n in sorted({r['cycle'] for r in slot['records']}):self.cycle.addItem(f'{n}회차',n)
                self.cycle.setCurrentIndex(max(0,self.cycle.findData(selected)))
        self.draw()

    def ent_data(self):
        records=self.slot['records'];mode=self.mode.currentIndex()
        if mode and records:
            cycle=max(r['cycle'] for r in records) if mode==1 else self.cycle.currentData()
            records=[r for r in records if r['cycle']==cycle]
        return pool_ent(records)

    def draw(self):
        if self.kind=='generic':return
        try:
            self.figure.clear()
            if self.kind=='ion':self.draw_ion()
            elif self.kind=='spam':self.draw_spam()
            else:self.draw_ent()
            self.figure.tight_layout(pad=1.5);self.canvas.draw_idle()
        except Exception as exc:self.summary.setText('결과 표시 오류: '+str(exc))

    def draw_ion(self):
        from labremote.ion_check.config import LABELS
        ax=self.figure.subplots();records=self.slot['records']
        for key,color in zip('abc',('#176eb5','#e68a2e','#8762ba')):
            # All retries remain visible; each cycle's final measurement forms its trend.
            x=[];y=[]
            for r in records:
                if not r['samples']:continue
                x.append(r['cycle']);y.append(r['samples'][-1]['counts'][key])
                ax.scatter([r['cycle']]*len(r['samples']),[s['counts'][key] for s in r['samples']],color=color,alpha=.28,s=15)
            ax.plot(x,y,'o-',color=color,label='369'+key.upper(),ms=4)
            threshold=records[0]['settings'].get('threshold_'+key) if records else None
            if threshold is not None:ax.axhline(threshold,ls='--',lw=.8,color=color,alpha=.5)
        ax.set(xlabel='Group cycle (faint dots: retries)',ylabel='PMTA + PMTC counts');ax.grid(alpha=.2);ax.legend(fontsize=8)
        samples=[s for r in records for s in r['samples']]
        normal=sum(bool(r['samples']) and r['samples'][-1]['decision']=='normal' for r in records)
        last=LABELS.get(samples[-1]['decision'],samples[-1]['decision']) if samples else '대기'
        self.summary.setText(f'정상 {normal}/{len(records)} 실행 · 최근 판정: {last} · 총 측정 {len(samples)} · 재측정 {sum(max(0,len(r["samples"])-1) for r in records)}\n흐린 점: 모든 측정 / 선: 실행별 마지막 측정 · DAC 연결 상태는 개별 결과 참조')

    def draw_spam(self):
        ax=self.figure.subplots();profiles={}
        for r in self.slot['records']:
            # Completed chamber runs only; interrupted SPAM is explicitly excluded.
            profiles.setdefault((r['chamber'],settings_key(r['settings'])),[]).append(r)
        summaries=[]
        for i,((chamber,profile),records) in enumerate(profiles.items()):
            valid=[r for r in records if r['status']=='completed']
            label=chamber+(' · '+profile[:4] if sum(k[0]==chamber for k in profiles)>1 else '')
            ax.plot([r['cycle'] for r in valid],[100*r['analysis']['spam_fidelity'] if r['analysis'].get('spam_fidelity') is not None else np.nan for r in valid],'o-',label=label,ms=4)
            pooled=pool_spam([r['analysis'] for r in valid]);f=pooled['spam_fidelity']
            summaries.append(label+' '+(f'{f:.2%}' if f is not None else '—'))
        excluded=sum(r['status']!='completed' for r in self.slot['records'])
        self.summary.setText('누적 fidelity: '+(' / '.join(summaries) or '대기')+f'\n상태별 오류/수신 수 합산 후 두 상태 동일 가중 · 미완료 실행 제외 {excluded}')
        ax.set(xlabel='Group cycle',ylabel='SPAM fidelity (%)');ax.grid(alpha=.2)
        if profiles:ax.legend(fontsize=8)

    def draw_ent(self):
        from labremote.entanglement.plotting import decay_fits,geometric_bins,decay_reference,COLORS
        from labremote.entanglement.config import nominal_trials
        self.cycle.setEnabled(self.mode.currentIndex()==2)
        c,d=self.ent_data();axes=self.figure.subplots(1,3)
        if d is None:
            self.summary.setText('얽힘 결과 대기 · 완료된 FPGA batch만 누적')
            for ax,title in zip(axes,('Decay counts','Coincidence','Attempts to herald · log bins')):ax.set_title(title,fontsize=10)
            return
        batches=len(d['batches']);elapsed=sum(b['elapsed_s'] for b in d['batches'])
        basis='ZZ' if c['basis']=='zz' else f"MW detuned · phase {c['phase_magnitude_deg']:g}°"
        self.summary.setText(f"{basis} · 완료 FPGA batch {batches} · 실제 시도 {d['attempts']:,} · herald {d['heralds']:,} · batch wall time {elapsed:.2f} s\n완료된 batch만 포함 (실패·중단 실행 안의 유효 완료 batch도 포함); 그룹 간 합산 없음")
        fits=decay_fits(d,c);ax=axes[0]
        for values,name,color in zip((d['a'],d['c'],np.asarray(d['a'])+d['c']),('PMTA','PMTC','Total'),COLORS):
            values=np.asarray(values);fit=fits[name];label=name
            if fit['status']=='completed':label+=f" τ={fit['tau_ns']:.2f} ns"
            ax.step(np.arange(120)*1.25,np.where(values>0,values,np.nan),where='mid',color=color,label=label)
            if fit['status']=='completed':
                x=np.linspace(fit['t0_ns'],148.75,160);ax.plot(x,fit['amplitude']*np.exp(-(x-fit['t0_ns'])/fit['tau_ns'])+fit['background'],'--',color=color)
        lower=max(0,min(c['decay_lower_a'],c['decay_lower_c'])-5)
        for cutoff in sorted({c['decay_lower_a'],c['decay_lower_c']}):ax.axvline(cutoff*1.25,color='gray',ls=':',lw=.8)
        ax.set_yscale('log');ax.set_ylim(.8,max(10,float(max(np.asarray(d['a'])+d['c']))*1.5));ax.set_xlim(lower*1.25,148.75)
        ax.set(title='Decay counts',xlabel='PMT - SYNC (ns)',ylabel='Counts / bin (log)');ax.legend(fontsize=7)
        ax=axes[1];w=c['coincidence_half_window_bins']*1.25
        ax.step((np.arange(240)-120)*1.25,d['coincidence'],where='mid',color='#7565b8')
        ax.axvspan(-w,w,color='#319270',alpha=.14);ax.set(title='Coincidence',xlabel='PMTC - PMTA (ns)',ylabel='Counts / bin',ylim=(0,max(1,max(d['coincidence'])*1.15)))
        ax=axes[2];edges,observed,expected=geometric_bins(d,nominal_trials(c))
        ax.bar(edges[:-1],observed,width=np.diff(edges),align='edge',alpha=.45,label='Observed / completed batches')
        ax.plot(np.sqrt(edges[:-1].astype(float))*np.sqrt(edges[1:].astype(float)),expected,'.-',color=COLORS[1],label='Geometric model')
        mean=decay_reference(d,c)['mean_trials']
        if mean:ax.axvline(mean,color='#cf4747',ls='--',label=f'Decay reference: {mean:.3g}')
        ax.set_xscale('log');ax.set_xlim(1,max(float(edges[-1]),mean*1.15 if mean else 1));ax.set_ylim(bottom=0)
        ax.set(title='Attempts to herald · log bins',xlabel='Attempt N (log; not seconds)',ylabel='Probability / log bin');ax.legend(fontsize=7)
        ax.text(.97,.96,f"Exhausted: {d['metrics']['exhausted_batches']}",transform=ax.transAxes,ha='right',va='top',fontsize=8)
        for ax in axes:ax.grid(alpha=.18);ax.title.set_fontsize(10)

    def open_full(self):
        from labremote.entanglement.plotting import EntanglementPlot
        c,d=self.ent_data()
        if d is None:return
        dialog=QtWidgets.QDialog(self);dialog.setWindowTitle(self.title()+' · '+self.mode.currentText());dialog.resize(1150,850)
        layout=QtWidgets.QVBoxLayout(dialog);scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);layout.addWidget(scroll)
        figure=Figure(figsize=(12,14));canvas=FigureCanvasQTAgg(figure);canvas.setMinimumSize(950,1150);scroll.setWidget(canvas)
        EntanglementPlot(figure,c).update(d);canvas.draw_idle();self.dialogs.append(dialog);dialog.show()


class GroupDashboard(QtWidgets.QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.state=None;self.snapshot=None;self.reader=None;self.store=ResultStore();self.pending=None;self.closed=False;self.panels={};self.selected=None;self.rendered_group=None;self.generation=0
        root=QtWidgets.QVBoxLayout(self);row=QtWidgets.QHBoxLayout();root.addLayout(row)
        self.heading=QtWidgets.QLabel('Queue를 설정하면 그룹별 모니터가 자동으로 구성됩니다.');self.heading.setWordWrap(True);row.addWidget(self.heading,1)
        self.follow=QtWidgets.QCheckBox('실행 중 그룹 따라가기');self.follow.setChecked(True);row.addWidget(self.follow)
        self.follow.toggled.connect(lambda _:self.show_snapshot() if self.snapshot else None)
        split=QtWidgets.QSplitter();root.addWidget(split,1);self.groups=QtWidgets.QListWidget();self.groups.setMinimumWidth(190);self.groups.setMaximumWidth(300);split.addWidget(self.groups)
        self.groups.currentRowChanged.connect(self.select_group);self.groups.itemClicked.connect(lambda _:self.follow.setChecked(False))
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);split.addWidget(scroll);body=QtWidgets.QWidget();scroll.setWidget(body);self.body=QtWidgets.QVBoxLayout(body)
        self.group_title=QtWidgets.QLabel();self.group_title.setWordWrap(True);self.body.addWidget(self.group_title)
        self.progress=QtWidgets.QProgressBar();self.body.addWidget(self.progress)
        self.panel_widget=QtWidgets.QWidget();self.panel_grid=QtWidgets.QGridLayout(self.panel_widget);self.body.addWidget(self.panel_widget)
        self.table=QtWidgets.QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['회차','Workflow','작업 반복','상태','측정 요약','시간(s)'])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers);self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents);self.table.horizontalHeader().setStretchLastSection(True);self.table.setMinimumHeight(190);self.body.addWidget(self.table)
        self.details=QtWidgets.QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(120);self.body.addWidget(self.details);self.table.itemSelectionChanged.connect(self.show_details)
        self.warning=QtWidgets.QLabel();self.warning.setWordWrap(True);root.addWidget(self.warning)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(1200);self.timer.timeout.connect(self.poll);self.timer.start()

    def accept(self,state):
        if self.closed:return
        identity=(state.get('queue_id'),state.get('folder'))
        if self.state is None or identity!=(self.state.get('queue_id'),self.state.get('folder')):
            self.generation+=1;self.selected=None;self.snapshot=None;self.rendered_group=None;self.store=ResultStore()
        self.state=deepcopy(state);self.pending=(self.generation,self.state)
        self.heading.setText(f"Queue · {state['status']} · 그룹별 독립 누적")
        self.launch()

    def poll(self):
        if self.state and self.state['status'] in ('running','paused') and not self.pending:
            self.pending=(self.generation,self.state);self.launch()

    def launch(self):
        if self.closed or self.pending is None or self.still_running():return
        generation,state=self.pending;self.pending=None
        self.reader=SnapshotReader(self.store,state,self)
        self.reader.loaded.connect(lambda snapshot,g=generation:self.loaded(g,snapshot))
        reader=self.reader
        self.reader.failed.connect(self.warning.setText);self.reader.finished.connect(lambda:self.reader_finished(reader));self.reader.start()

    def reader_finished(self,reader):
        if self.reader is reader:self.reader=None
        reader.deleteLater();self.launch()

    def loaded(self,generation,snapshot):
        if self.closed or generation!=self.generation:return
        self.snapshot=snapshot;self.show_snapshot()

    def show_snapshot(self):
        groups=self.snapshot['groups'];state=self.snapshot['state']
        if self.follow.isChecked():
            active=next((group_key(s) for s in state['steps'] if s['status']=='running'),None)
            if active:self.selected=active
        keys=[g['key'] for g in groups]
        if self.selected not in keys:self.selected=keys[0] if keys else None
        with QtCore.QSignalBlocker(self.groups):
            self.groups.clear()
            for g in groups:
                cycles={s.get('group_iteration',s['job_repeat']) for s in g['steps']}
                done=sum(all(s['status']=='completed' for s in g['steps'] if s.get('group_iteration',s['job_repeat'])==c) for c in cycles)
                status='실행 중' if any(s['status']=='running' for s in g['steps']) else '실패' if any(s['status']=='failed' for s in g['steps']) else '완료' if done==len(cycles) else '대기/중단'
                self.groups.addItem(f"{g['name']}\n전체 반복 {g['iteration']} · {status} · {done}/{len(cycles)}회 완료")
            self.groups.setCurrentRow(keys.index(self.selected) if self.selected in keys else -1)
        self.warning.setText('\n'.join(self.snapshot['warnings'][:4]));self.render_group()

    def select_group(self,index):
        if self.snapshot and 0<=index<len(self.snapshot['groups']):
            self.selected=self.snapshot['groups'][index]['key'];self.render_group()

    def render_group(self):
        group=next((g for g in self.snapshot['groups'] if g['key']==self.selected),None) if self.snapshot else None
        if group is None:
            while self.panel_grid.count():
                widget=self.panel_grid.takeAt(0).widget()
                if widget:widget.hide();widget.deleteLater()
            self.panels={};self.group_title.clear();self.table.setRowCount(0);self.details.clear();self.progress.setValue(0);return
        identity=(self.generation,self.selected)
        slots=group['slots'];keys=[(s['job_id'],s['kind'],s['profile']) for s in slots]
        if self.rendered_group!=identity or set(keys)!=set(self.panels):
            while self.panel_grid.count():
                item=self.panel_grid.takeAt(0)
                if item.widget():item.widget().hide();item.widget().deleteLater()
            self.panels={};row=0;column=0
            for slot in sorted(slots,key=lambda s:s['kind']=='ent'):
                key=slot['job_id'],slot['kind'],slot['profile'];panel=WorkflowPanel(slot);self.panels[key]=panel
                if slot['kind']=='ent':
                    if column:row+=1;column=0
                    self.panel_grid.addWidget(panel,row,0,1,2);row+=1
                else:
                    self.panel_grid.addWidget(panel,row,column);column+=1
                    if column==2:row+=1;column=0
            self.rendered_group=identity
        else:
            for slot,key in zip(slots,keys):self.panels[key].update_slot(slot)
        self.group_title.setText(f"{group['name']} · 전체 반복 {group['iteration']}\n그룹/Queue 항목별 누적 · 설정이 달라진 결과는 별도로 표시합니다.")
        cycles={s.get('group_iteration',s['job_repeat']) for s in group['steps']}
        done=sum(all(s['status']=='completed' for s in group['steps'] if s.get('group_iteration',s['job_repeat'])==c) for c in cycles)
        active=next((s['name'] for s in group['steps'] if s['status']=='running'),'')
        self.progress.setRange(0,len(cycles));self.progress.setValue(done);self.progress.setFormat(f'{done}/{len(cycles)}회 완료'+(' · '+active if active else ''))
        self.group=group;selected=self.table.currentRow();self.table.setRowCount(len(group['steps']))
        for i,s in enumerate(group['steps']):
            records=[r for slot in slots for r in slot['records'] if r['step_id']==s['step_id']];parts=[]
            for r in records:
                if r['kind']=='ion' and r['samples']:parts.append(r['samples'][-1]['decision']+f" ({len(r['samples'])} measurements)")
                elif r['kind']=='spam':
                    f=r['analysis'].get('spam_fidelity');parts.append(r['chamber']+' '+(f'{f:.2%}' if f is not None else '—'))
                elif r['kind']=='ent':parts.append(f"{sum(b['heralded'] for b in r['batches'])} herald / {sum(b['attempts'] for b in r['batches']):,} trials")
            if not parts:parts=[s.get('result',{}).get('reason',s.get('reason',''))]
            values=[s.get('group_iteration',s['job_repeat']),s['name'],s['job_repeat'],s['status'],' · '.join(parts),f"{s['elapsed_s']:.2f}" if 'elapsed_s' in s else '']
            for col,v in enumerate(values):self.table.setItem(i,col,QtWidgets.QTableWidgetItem(str(v)))
        if 0<=selected<self.table.rowCount():self.table.selectRow(selected)
        self.show_details()

    def show_details(self):
        i=self.table.currentRow()
        self.details.setPlainText(json.dumps(self.group['steps'][i],ensure_ascii=False,indent=2)[:30000] if hasattr(self,'group') and 0<=i<len(self.group['steps']) else '')

    def still_running(self):return self.reader is not None and self.reader.isRunning()
    def shutdown(self):self.closed=True;self.pending=None;self.timer.stop()
    def closeEvent(self,event):
        self.shutdown()
        if self.reader:self.reader.wait()
        super().closeEvent(event)
