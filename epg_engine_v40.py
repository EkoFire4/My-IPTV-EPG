#!/usr/bin/env python3
"""Development-only metadata fallback; run beside unchanged V3.7.1 modules."""
import csv, gzip, json, os, tempfile
from collections import Counter, defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET
import playlist_metadata as meta
import update_epg as v37

e = v37.engine
records = v37.v36.v35.records
baseline = json.loads(Path('v37-baseline.json').read_text())['matches']
assert len(baseline) == 675
v37.baseline = json.loads(v37.BASELINE.read_text())
v37.reviewed = json.loads(v37.REVIEW.read_text())['channels']
assert len(v37.baseline['matches']) == 645
old_read, old_load, old_match = e.read_playlist, e.load_epg_sources, e.match_channel
metadata, index, review = {}, defaultdict(list), []
counts = Counter()

def read_playlist():
    original = e.download
    raw = original(e.M3U_URL)

    if isinstance(raw, str):
        raw = raw.encode('utf-8')

    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)

    e.download = lambda url: (
        raw if url == e.M3U_URL else original(url)
    )

    try:
        channels = old_read()
    finally:
        e.download = original

    content = raw.decode('utf-8-sig', errors='replace')

    counts['playlist_bytes'] = len(raw)
    counts['playlist_extinf'] = sum(
        line.strip().upper().startswith('#EXTINF')
        for line in content.splitlines()
    )
    counts['engine_channels'] = len(channels)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'playlist.m3u'
        path.write_bytes(raw)
        rows = list(meta.parse(path))

    counts['metadata_parsed'] = len(rows)

    ids = Counter(
        r['tvg_id'] for r in rows if r['tvg_id']
    )

    counts['metadata_duplicate_ids'] = sum(
        n > 1 for n in ids.values()
    )

    engine_ids = {str(cid) for cid in channels}

    metadata.clear()

    for r in rows:
        cid = r['tvg_id']

        if not cid or ids[cid] != 1:
            continue

        if cid not in engine_ids:
            continue

        meta.classify_event(r)

        (
            r['identity_name'],
            r['identity_key'],
            r['alias_candidates']
        ) = meta.identity(r)

        metadata[cid] = r

    counts['metadata_unique'] = len(metadata)

    counts['metadata_identity_eligible'] = sum(
        bool(r['identity_key'])
        for r in metadata.values()
    )

    counts['metadata_unreconciled'] = len(
        set(ids) - engine_ids
    )

    coverage = (
        100 * len(metadata) / len(engine_ids)
        if engine_ids else 0
    )

    counts['metadata_coverage_percent'] = round(
        coverage, 2
    )

    print('\n===== V4.1 METADATA DIAGNOSTICS =====')
    print(json.dumps(dict(counts), indent=2))

    report_dir = Path('reports')
    report_dir.mkdir(exist_ok=True)

    (report_dir / 'v40-ingestion.json').write_text(
        json.dumps(dict(counts), indent=2),
        encoding='utf-8'
    )

    if coverage < 95:
        raise RuntimeError(
            'Metadata ingestion gate failed: '
            'less than 95% channel reconciliation.'
        )

    if not counts['metadata_identity_eligible']:
        raise RuntimeError(
            'No eligible metadata identities recovered.'
        )

    print('METADATA INGESTION GATE PASSED')

    return channels

def load_sources(*args, **kwargs):
    entries = old_load(*args, **kwargs)
    for item in entries:
        if item.get('event') or not item.get('region'): continue
        for key in item.get('keys', []):
            index[item['region'], key].append(item)
    return entries

def match(channel, indexes, mappings):
    result, method, candidates = old_match(channel, indexes, mappings)
    cid = str(channel['id'])
    if result or cid in baseline: return result, method, candidates
    r = metadata.get(cid)
    if not r or not r['identity_key'] or channel.get('heading') or channel.get('ambiguous_region'):
        return result, method, candidates
    region = r['region']
    if channel.get('region') not in ('', None, 'unknown', region): return result, method, candidates
    if channel.get('event') and r['event_class'] != 'permanent_candidate': return result, method, candidates
    if method not in ('no_compatible_candidate','unknown_region_requires_review','no_match','schedule_ambiguity'):
        return result, method, candidates
    key = e.normalise_name(r['identity_name'].replace(' [ultra]',''), region)
    if not key: return result, method, candidates
    pool = {v37.source_key(x):x for x in index.get((region,key), [])}
    # Require explicit quality compatibility for UHD; never use UHD for ordinary feeds.
    q = {v37.quality(n) for n in channel['names']} - {''}
    if len(q)>1: return result, method, candidates
    wanted = next(iter(q), '')
    def compatible(x):
        qualities = {v37.quality(n) for n in set(x.get('names',[])) | {x['id']}} - {''}
        return len(qualities)<=1 and (('uhd' in qualities) == (wanted=='uhd')) and (not wanted or not qualities or wanted in qualities)
    suitable = [x for x in pool.values() if compatible(x)]
    suitable.sort(key=lambda x:(-len(x['programmes']),v37.source_key(x)))
    if not suitable or (len(suitable)>1 and not all(v37.agree(suitable[0],x) for x in suitable[1:])):
        counts['metadata_unresolved'] += 1
        if pool: review.append({'channel_id':cid,'region':region,'candidate_count':len(pool),'reason':'quality_or_schedule_ambiguity'})
        return result, method, candidates
    best = suitable[0]
    rec = records[cid]
    rec.pop('reason',None); rec.pop('candidates',None)
    rec.update(status='matched',method='metadata_exact',epg_id=v37.v36.safe(best['id']),source=v37.v36.source_name(best['source']),region=region)
    counts['metadata_matches'] += 1
    return best,'metadata_exact',[]

def save(root):
    out = Path('reports'); out.mkdir(exist_ok=True)
    ids = [x.get('id') for x in root.findall('channel')]
    programme_ids = {x.get('channel') for x in root.findall('programme')}
    matched = {cid:{'epg_id':r['epg_id'],'source':v37.v36.source_name(r['source'])} for cid,r in records.items() if r['status']=='matched' and cid in ids}
    lost = sorted(baseline.keys()-matched.keys()); gained = sorted(matched.keys()-baseline.keys())
    changed = [k for k in sorted(baseline.keys() & matched.keys()) if baseline[k]!=matched[k]]
    ok = not lost and not changed and len(ids)==len(set(ids))==len(matched) and set(ids)==programme_ids and bool(ids)
    report = dict(version='4.1',test_mode=True,matched_channels=len(matched),programmes=len(root.findall('programme')),gained=gained,lost=lost,changed=changed,gate_passed=ok,counts=dict(counts),matches=matched,review=review)
    (out/'v40-diagnostics.json').write_text(json.dumps(report,indent=2))
    print('V4.0:',len(matched),'gained:',len(gained),'lost:',len(lost),'changed:',len(changed),'gate:',ok)
    if not ok: raise RuntimeError('Regression gate failed; production untouched')
    data = ET.tostring(root,encoding='utf-8',xml_declaration=True)
    if not e.M3U_URL or e.M3U_URL.encode() in data: raise RuntimeError('Privacy gate failed')
    # Only development output; never invoke legacy production save.
    path = Path('epgs/development-v40.xml.gz'); path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix('.tmp'); tmp.write_bytes(gzip.compress(data,mtime=0)); tmp.replace(path)

if __name__ == '__main__':
    e.VERSION='4.1'; e.TEST_MODE=True
    e.read_playlist=read_playlist; e.load_epg_sources=load_sources; e.match_channel=match; e.save_epg=save
    e.main()
