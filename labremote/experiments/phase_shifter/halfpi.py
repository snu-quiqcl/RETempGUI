"""Code-indexed half-pi times inferred from saved phase Rabi fits."""
import bisect
import hashlib
import json
import math
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path


def load(path):
    raw=Path(path).read_text(encoding='utf-8-sig')
    snapshot=dict(path=str(path),json=raw,sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest(),method='halfpi_time_linear_v1')
    knots(snapshot)
    return snapshot


def knots(snapshot):
    if snapshot.get('method')!='halfpi_time_linear_v1':raise ValueError('지원하지 않는 π/2 보간 방식')
    raw=snapshot['json']
    if hashlib.sha256(raw.encode('utf-8')).hexdigest()!=snapshot['sha256']:raise ValueError('Rabi 원본 데이터 해시 불일치')
    return _knots(raw)


@lru_cache(maxsize=4)
def _knots(raw):
    data=json.loads(raw)
    if data.get('experiment')!='phase_rabi':raise ValueError('위상별 Rabi의 result.json을 선택하세요.')
    phases=data['phases'];fits=data['fits'];records={};grouped={};excluded=[]
    for fit in fits:
        i=fit['phase_index']
        if type(i) is not int or not 0<=i<len(phases) or i in records:raise ValueError('Rabi fit phase_index 오류')
        records[i]=fit
    for i,p in enumerate(phases):
        code=p['code']
        if type(code) is not int or not 0<=code<=4095:raise ValueError('Rabi 코드 범위 오류')
        f=records.get(i,{})
        freq=f.get('frequency_khz');error=f.get('error_khz')
        good=(f.get('valid') is True and type(freq) in (int,float) and math.isfinite(freq) and freq>0
              and type(error) in (int,float) and math.isfinite(error) and 0<=error<=freq*.25)
        # Missing/failed or poorly determined fits remain barriers to interpolation.
        value=250/freq if good else None
        grouped.setdefault(code,[]).append(value)
    result=[]
    for code,values in sorted(grouped.items()):
        if any(v is None for v in values):
            result.append((code,None));excluded.append(code);continue
        if max(values)-min(values)>.1*(sum(values)/len(values)):
            raise ValueError(f'코드 {code}: 반복 Rabi 결과의 π/2 시간이 10% 이상 다릅니다. 드리프트를 확인하세요.')
        result.append((code,sum(values)/len(values)))
    if not result or result[0][0]!=0 or result[0][1] is None:
        raise ValueError('첫 π/2 기준인 코드 0의 유효한 Rabi 피팅이 필요합니다.')
    # Only a measured full-turn endpoint permits periodic boundary interpolation.
    if any(p.get('requested_angle_deg')==360 and p['code']==0 for p in phases):
        result.append((4096,result[0][1]))
    if len(result)<2:raise ValueError('보간에 필요한 Rabi 지점이 부족합니다.')
    return tuple(result)


def time_at(code,snapshot):
    table=knots(snapshot);codes=[p[0] for p in table]
    i=bisect.bisect_left(codes,code)
    if i<len(table) and table[i][0]==code:
        time=table[i][1];bounds=[code,code]
    elif i==0 or i==len(table):raise ValueError(f'코드 {code}: Rabi 측정 범위 밖입니다.')
    else:
        lo,a=table[i-1];hi,b=table[i]
        if a is None or b is None:raise ValueError(f'코드 {code}: 인접 Rabi 피팅이 유효하지 않습니다 ({lo}~{hi}).')
        # Avoid bridging sparse/missing angular regions wider than 45 nominal degrees.
        if hi-lo>512:raise ValueError(f'코드 {code}: 보간 간격이 너무 큽니다 ({hi-lo} codes > 512).')
        time=a+(b-a)*(code-lo)/(hi-lo);bounds=[lo,hi]
    if time is None:raise ValueError(f'코드 {code}: Rabi 피팅 실패 또는 주파수 오차 >25%.')
    clocks=int((Decimal(str(time))*100).to_integral_value(rounding=ROUND_HALF_UP))
    if not 3<=clocks<=65538:raise ValueError(f'코드 {code}: π/2 시간이 지원 범위 0.03~655.38 µs 밖입니다.')
    return dict(clocks=clocks,estimated_us=time,applied_us=clocks/100,bounds=bounds)


def apply(point,snapshot):
    first=time_at(0,snapshot);second=time_at(point['code'],snapshot)
    return dict(point,half_pi_first_clocks=first['clocks'],half_pi_second_clocks=second['clocks'],
        half_pi_first_us=first['applied_us'],half_pi_second_us=second['applied_us'],
        half_pi_second_estimated_us=second['estimated_us'],half_pi_bracket_codes=second['bounds'],
        rabi_source_sha256=snapshot['sha256'])
