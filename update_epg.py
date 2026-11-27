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
                exact[k].add(i)
                if len(k) >= 5:
                    prefix[k[:4]].add(i)
    rows = []
    for r in records:
        if r['status'] != 'unmatched' or r.get('event') or r.get('heading'):
            continue
        keys = r.get('normalised_names', [])
        pool = set()
        for k in keys:
            pool.update(exact.get(k, ()))
            if len(k) >= 5:
                pool.update(prefix.get(k[:4], ()))
        # For Arabic hints, compare the language-prefix-stripped name too.
        if r.get('language_hint') == 'ar':
            k = engine.normalise_name(r['name'], '')
            if k:
                keys = list(set(keys) | {k})
                pool.update(exact.get(k, ()))
                pool.update(prefix.get(k[:4], ()))
        ranked = []
        for i in pool:
            e = catalogue[i]
            if e['event']:
                continue
            score = max((SequenceMatcher(None, a, b).ratio() for a in keys for b in e['keys']), default=0)
            if score < .88:
                continue
            compatible = r['region'] == e['region'] and r['region'] != 'unknown'
            ranked.append((score, compatible, i))
        for score, compatible, i in sorted(ranked, key=lambda x: (-x[0], -int(x[1]), x[2]))[:5]:
            e = catalogue[i]
            rows.append({'channel_id': r['channel_id'], 'name': r['name'], 'region': r['region'],
                         'language_hint': r.get('language_hint', ''), 'epg_id': e['epg_id'],
                         'source': e['source'], 'candidate_region': e['region'],
                         'score': round(score, 3), 'same_region': compatible,
                         'review_only': True})
    return rows

def regression(records):
    if not BASELINE.exists():
        return {'available': False, 'reason': 'baseline missing'}
    old = json.loads(BASELINE.read_text(encoding='utf-8'))
    if old.get('version') != '3.5' or len(old.get('matches', {})) != 641:
        raise ValueError('Unexpected V3.5 baseline')
    a = old['matches']
    b = {str(r['channel_id']): {'epg_id': r['epg_id'], 'source': source_name(r['source'])}
         for r in records if r['status'] == 'matched'}
    return {'available': True, 'gained': sorted(b.keys()-a.keys()),
            'lost': sorted(a.keys()-b.keys()),
            'changed': [{'channel_id': k, 'old': a[k], 'new': b[k]} for k in sorted(a.keys() & b.keys()) if a[k] != b[k]],
            'retained': len(a.keys() & b.keys())}

def save_epg(root):
    records = list(v35.records.values())
    matched = len(root.findall('channel'))
    if matched != sum(r['status'] == 'matched' for r in records):
        raise RuntimeError('Diagnostic count differs from XML output')
    # Keep diagnostic source names, not URLs.
    for r in records:
        if 'source' in r:
            r['source'] = source_name(r['source'])
    review = suggestions(records)
    comparison = regression(records)
    eligible = [r for r in records if r['status'] != 'excluded']
    regular = [r for r in eligible if not r.get('event')]
    report = {'version': '3.6', 'test_mode': True, 'matched_channels': matched,
              'baseline_channels': 641, 'net_improvement': matched-641,
              'programmes': len(root.findall('programme')), 'total_records': len(records),
              'distinct_identities': len({(r['source'], r['epg_id']) for r in records if r['status']=='matched'}),
              'eligible_channels': len(eligible), 'regular_channels': len(regular),
              'adjusted_coverage': round(100*matched/max(1,len(eligible)),2),
              'regular_coverage': round(100*sum(r['status']=='matched' for r in regular)/max(1,len(regular)),2),
              'source_catalogue_entries': len(catalogue), 'extra_sources': extra_sources,
              'suggested_channel_ids': len({r['channel_id'] for r in review}),
              'diagnostics': dict(Counter(r.get('reason',r['status']) for r in records)),
              'comparison': comparison, 'match_records': records}
    (REPORT/'v36-diagnostics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    write_csv('v36-source-catalogue.csv', catalogue, ['epg_id','source','region','names','keys','event','programmes'])
    write_csv('v36-review-candidates.csv', review, ['channel_id','name','region','language_hint','epg_id','source','candidate_region','score','same_region','review_only'])
    fields = ['channel_id','name','region','event','heading','language_hint','status','method','epg_id','source','reason','normalised_names','candidates']
    write_csv('v36-matched.csv', [r for r in records if r['status']=='matched'], fields)
    write_csv('v36-unmatched.csv', [r for r in records if r['status']=='unmatched'], fields)
    print('\n===== V3.6 DEVELOPMENT RESULTS =====')
    for k,v in report.items():
        if k not in ('match_records','comparison','extra_sources'):
            print(f'{k}: {v}')
    print('\n===== V3.6 REGRESSION ANALYSIS =====')
    if comparison['available']:
        for k in ('gained','lost','changed'):
            print(f'{k}: {len(comparison[k])}')
        print('retained:', comparison['retained'])
    else:
        print(comparison['reason'])
    engine.TEST_MODE = True
    v35.original_save(root)
    print('PRODUCTION EPG NOT MODIFIED.')

engine.save_epg = save_epg

if __name__ == '__main__':
    print('VERSION 3.6 — DEVELOPMENT ONLY')
    engine.main()
