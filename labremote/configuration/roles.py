"""Experiment role mapping; loaded once when scan windows are constructed."""
import json
from .paths import CONFIG_ROOT

def scan_roles():
    path=CONFIG_ROOT/'operations/scan_roles.local.json'
    if not path.exists():path=CONFIG_ROOT/'operations/scan_roles.json'
    rows=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(rows,list) or len(rows)!=4:raise ValueError('Exactly four scan roles are required')
    for row in rows:
        if not isinstance(row,dict) or set(row)-{'pmt_index'}!={'title','axes'}:raise ValueError('Invalid scan role fields')
        if not isinstance(row['title'],str) or not row['title'].strip():raise ValueError('Scan title is required')
        axes=row['axes']
        if not isinstance(axes,list) or len(axes)!=3 or any(not isinstance(n,str) or not n.isidentifier() for n in axes) or len(set(axes))!=3:raise ValueError('Scan role needs three distinct motor names')
        # Historical PMT indices are ignored; each scan selects a common nickname.
        row.pop('pmt_index',None)
    return rows
