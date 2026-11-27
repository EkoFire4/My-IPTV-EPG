#!/usr/bin/env python3
"""V3.6 development wrapper; requires the existing V3.2–V3.5 engines."""
import csv
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit

import epg_engine_v35 as v35

engine = v35.engine
engine.VERSION = '3.6'
engine.TEST_MODE = True
engine.MIN_MATCHED_CHANNELS = 641
engine.OUTPUT_FILE = Path('epgs/development-v36.xml.gz')
REPORT = Path('reports')
REPORT.mkdir(exist_ok=True)
BASELINE = Path('v35-baseline.json')
MAX_EXTRA_SOURCES = 20
EXTRA_REGIONS = {'UK','IE','US','CA','DE','AT','NL','AR','AE','QA','SA','EG','KW','OM','BH','JO','LB','MA','DZ','TN','BR','RO','RS','ES','IT','FR','PL','AU','PK'}
old_discover = engine.discover_sources
old_load = engine.load_epg_sources
catalogue = []
extra_sources = []

def safe(value):
    return v35.safe(value)

def source_name(value):
    return safe(urlsplit(str(value)).path.rsplit('/', 1)[-1])

def discover_sources(*args, **kwargs):
    urls = list(old_discover(*args, **kwargs))
    try:
        raw = engine.download(engine.BASE)
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8', errors='replace')
        names = set(re.findall(r'epg_ripper_([A-Z0-9_]+)\.xml\.gz', raw))
        existing = {source_name(u) for u in urls}
        candidates = []
        for name in sorted(names):
            filename = f'epg_ripper_{name}.xml.gz'
            if filename in existing or 'DUMMY' in name:
                continue
            region = re.match(r'^([A-Z]{2})(?:\d|_)', name)
            if (region and region.group(1) in EXTRA_REGIONS) or name.startswith(('BEIN','DAZN','SPORTKLUB','DIRECTVSPORTS')):
                candidates.append(filename)
        for filename in candidates[:MAX_EXTRA_SOURCES]:
            urls.append(engine.BASE.rstrip('/') + '/' + filename)
            extra_sources.append(filename)
    except Exception as exc:
        print('Additional discovery unavailable:', type(exc).__name__)
    print('\n===== V3.6 SOURCE DISCOVERY =====')
    print('Additional sources selected:', len(extra_sources))
    for name in extra_sources:
        print(name)
    print('Total configured sources:', len(urls))
    return urls

engine.discover_sources = discover_sources

def load_sources(*args, **kwargs):
    entries = old_load(*args, **kwargs)
    for e in entries:
        catalogue.append({'epg_id': safe(e['id']), 'source': source_name(e['source']),
                          'region': e.get('region') or 'unknown',
                          'names': sorted(safe(n) for n in e.get('names', [])),
                          'keys': sorted(safe(k) for k in e.get('keys', [])),
                          'event': bool(e.get('event')), 'programmes': len(e.get('programmes', []))})
    return entries

engine.load_epg_sources = load_sources

def write_csv(name, rows, fields):
    with (REPORT / name).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            out = {}
            for k in fields:
                val = row.get(k, '')
                if isinstance(val, (list, dict)):
                    val = json.dumps(val, ensure_ascii=False)
                if isinstance(val, str) and val.lstrip().startswith(('=', '+', '-', '@')):
                    val = "'" + val
                out[k] = val
            writer.writerow(out)

def suggestions(records):
    exact = defaultdict(set)
    prefix = defaultdict(set)
    for i, e in enumerate(catalogue):
        for k in e['keys']:
            if k:
