"""Explicit, frozen empirical inverse table; no extrapolation or unsafe fallback."""
import csv
import io
import hashlib
import math
import json
from functools import lru_cache
from pathlib import Path
from PyQt5 import QtCore, QtWidgets


@lru_cache(maxsize=4)
def data_model(raw):
    from .interpolation import fit
    return fit(json.loads(raw.lstrip('\ufeff')))


def rows(snapshot):
    raw = snapshot['csv']
    if hashlib.sha256(raw.encode('utf-8')).hexdigest() != snapshot['sha256']:
        raise ValueError('보정표 내용과 SHA256이 일치하지 않습니다.')
    if snapshot.get('kind') == 'ramsey_data_interpolation':
        return data_model(raw)
    result = {}
    for row in csv.DictReader(io.StringIO(raw.lstrip('\ufeff'))):
        angle = float(row['target_deg'])
        if not math.isfinite(angle) or not 0 <= angle <= 360 or angle in result:
            raise ValueError('보정표 각도 범위 또는 중복 오류')
        quality = row['quality']
        if quality not in ('conditional_candidate', 'reference_anchor', 'low_sensitivity', 'ambiguous_plateau'):
            raise ValueError('알 수 없는 보정표 quality')
        code = None
        phase = None
        if quality == 'conditional_candidate':
            code = int(row['recommended_test_code'])
            phase = float(row['model_phase_deg'])
            if not 0 <= code <= 4095 or code != int(row['candidate_code']) or not math.isfinite(phase) or not 0 <= phase <= 360:
                raise ValueError('보정표 코드 또는 모델 각도 오류')
        elif quality == 'reference_anchor':
            if angle not in (0, 360) or int(row['candidate_code']) != 0:
                raise ValueError('보정표 기준점 오류')
            code, phase = 0, 0.
        elif row['recommended_test_code'].strip():
            raise ValueError('불확실 구간에 적용 코드가 지정되어 있습니다.')
        result[angle] = (code, phase, quality)
    if not result:
        raise ValueError('빈 보정표입니다.')
    return result


def load(path):
    raw = Path(path).read_text(encoding='utf-8')
    snapshot = dict(path=str(path), csv=raw, sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest())
    if Path(path).suffix.lower() == '.json':
        snapshot['kind'] = 'ramsey_data_interpolation'
    rows(snapshot)
    return snapshot


def resolve(angle, snapshot=None):
    from .config import phase_point
    point = phase_point(angle)
    if snapshot is None:
        return point
    table = rows(snapshot)
    if snapshot.get('kind') == 'ramsey_data_interpolation':
        from .interpolation import resolve as interpolate
        return dict(interpolate(angle, table), calibration_sha256=snapshot['sha256'])
    if angle not in table:
        raise ValueError(f'{angle:g}°: 보정표에 없는 각도입니다. 표의 각도만 입력하세요.')
    code, phase, quality = table[angle]
    if code is None:
        raise ValueError(f'{angle:g}°: 보정 적용 불가 ({quality})')
    return dict(requested_angle_deg=float(angle), code=code, applied_angle_deg=phase,
                conversion_mode='empirical_conditional', calibration_sha256=snapshot['sha256'], quality=quality)


def estimate_note(point):
    quality = point.get('quality')
    if quality == 'plateau_midpoint_assumption':
        low, high = point['plateau_code_interval']
        return f'\n평탄 구간: 코드 {low}~{high}의 중간값 선택 (위상 확정 불가)'
    if quality == 'low_sensitivity_interpolated':
        return '\n저감도 구간 보간값 · 실제 위상은 재측정 필요'
    if quality == 'interpolated_conditional':
        return '\n실험 데이터 보간 · 조건부 추정'
    return ''


class CalibrationSelector(QtWidgets.QGroupBox):
    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__('각도 → 코드 변환', parent)
        self.snapshot = None
        layout = QtWidgets.QVBoxLayout(self)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(['선형 변환 · 보정 없음', '선택한 실험 데이터 / 보정표 사용'])
        layout.addWidget(self.mode)
        self.choose = QtWidgets.QPushButton('실험 데이터 JSON / 보정표 CSV 선택…')
        layout.addWidget(self.choose)
        self.info = QtWidgets.QLabel('보정표 미선택')
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        note = QtWidgets.QLabel('JSON: 실험 데이터 기반 선형 보간 · 소수 각도 및 저감도 구간 포함\n평탄 구간은 코드 범위의 중간값 사용 · 실제 위상은 추가 측정 필요\n기존 CSV: 표에 있는 유효 각도만 적용')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.mode.currentIndexChanged.connect(self.changed)
        self.choose.clicked.connect(self.open)

    def active(self):
        if not self.mode.currentIndex():
            return None
        if self.snapshot is None:
            raise ValueError('실험 데이터 JSON 또는 보정표 CSV를 먼저 선택하세요.')
        return self.snapshot

    def set_table(self, snapshot):
        if snapshot is not None:
            rows(snapshot)
        self.snapshot = snapshot
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(int(snapshot is not None))
        self.mode.blockSignals(False)
        self.info.setText(Path(snapshot['path']).name + '\nSHA256: ' + snapshot['sha256'][:16] if snapshot else '보정표 미선택')
        if snapshot and snapshot.get('kind') == 'ramsey_data_interpolation':
            self.info.setText(self.info.text() + '\n실험 데이터 보간 활성 · 0~360° 전체 범위 (조건부 추정)')
        self.changed.emit()

    def open(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '실험 데이터 / 보정표 선택', str(Path(__file__).parent/'calibrations'), 'Ramsey 실험 데이터 (*.json);;기존 보정표 (*.csv)')
        if path:
            try:
                self.set_table(load(path))
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, '보정표 오류', str(exc))
