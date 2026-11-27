#!/usr/bin/env python3
"""V3.7.1 development wrapper for the existing V3.2–V3.6 engines."""
import json
import re
from pathlib import Path
from collections import defaultdict, Counter
import epg_engine_v36 as v36

engine = v36.engine
engine.VERSION = '3.7.1'
engine.TEST_MODE = True
engine.MIN_MATCHED_CHANNELS = 645
engine.OUTPUT_FILE = Path('epgs/development-v37.xml.gz')
REPORT = Path('reports')
BASELINE = Path('v36-baseline.json')
REVIEW = Path('v37-reviewed-candidates.json')
old_load = engine.load_epg_sources
old_match = engine.match_channel
live = defaultdict(list)
resolutions = []
baseline_restorations = []
identity_index = defaultdict(list)
rejections = Counter()

def quality(value):
    s = engine.clean_text(value)
    if re.search(r'(?<![a-z0-9])(?:4k|uhd|2160p)(?![a-z0-9])', s):
        return 'uhd'
    if re.search(r'(?<![a-z0-9])(?:fhd|hd|1080p|720p)(?![a-z0-9])', s):
        return 'hd'
    if re.search(r'(?<![a-z0-9])sd(?![a-z0-9])', s):
        return 'sd'
    return ''

def source_key(e):
    return (v36.source_name(e['source']), str(e['id']))

def load_sources(*args, **kwargs):
    entries = old_load(*args, **kwargs)
    live.clear()
    identity_index.clear()
    for e in entries:
        identity_index[source_key(e)].append(e)
        for key in e.get('keys', []):
            live[e.get('region',''), key].append(e)
    return entries

engine.load_epg_sources = load_sources

def agree(a,b):
    # Require substantial common schedule evidence, not just a few titles.
    x = engine.schedule_signature(a)
    y = engine.schedule_signature(b)
    # Engine signatures are sets of (start, title) pairs.
    x, y = dict(x), dict(y)
    common = x.keys() & y.keys()
    return (len(common) >= 8 and len(common)/max(1,min(len(x),len(y))) >= .75
            and sum(x[k] == y[k] for k in common)/len(common) >= .95)

def match_channel(channel, indexes, mappings):
    result, method, candidates = old_match(channel,indexes,mappings)
    cid = str(channel['id'])
    # Preserve a prior source only when the current engine already accepts
    # a compatible match and the old source has corroborating live schedules.
    prior = baseline['matches'].get(cid)
    if result and prior and source_key(result) != (prior['source'], prior['epg_id']):
        region = channel.get('region', '')
        keys = set(channel.get('keys', []))
        originals = identity_index.get((prior['source'], prior['epg_id']), [])
        if (len(originals) == 1 and region and not channel.get('ambiguous_region')
                and not channel.get('event') and not channel.get('heading')):
            original = originals[0]
            if (original.get('region') == result.get('region') == region
                    and not original.get('event') and not result.get('event')
                    and keys.intersection(original.get('keys', []))
                    and keys.intersection(result.get('keys', []))
                    and agree(original, result)):
                record = v36.v35.records[cid]
                baseline_restorations.append(dict(channel_id=cid, name=record['name'],
                    previous_candidate=dict(epg_id=v36.safe(result['id']), source=v36.source_name(result['source'])),
                    restored=prior))
                record.update(epg_id=prior['epg_id'], source=prior['source'])
                return original, method, []
        rejections['baseline_change_not_verified'] += 1
    if result or method != 'schedule_ambiguity' or channel.get('event') or channel.get('heading') or channel.get('ambiguous_region'):
        return result,method,candidates
    row = reviewed.get(cid)
    region = channel.get('region','')
    keys = set(channel.get('keys',[]))
    if not row or not region or row['region'] != region or keys != set(row['keys']):
        rejections['not_reviewed_or_identity_changed'] += 1
        return result,method,candidates
    q = {quality(n) for n in channel['names']} - {''}
    if len(q) != 1:
        rejections['quality_unspecified_or_conflicting'] += 1
        return result,method,candidates
    q = next(iter(q))
    pool = {source_key(e):e for k in keys for e in live.get((region,k),[]) if not e.get('event')}
    allowed = {tuple(p) for p in row['candidates']}
    if set(pool) != allowed:
        rejections['candidate_set_changed'] += 1
        return result,method,candidates
    suitable = [e for e in pool.values() if quality(e['id']) == q and all(quality(n) in ('',q) for n in e.get('names',[]))]
    if not suitable:
        rejections['no_explicit_quality_match'] += 1
        return result,method,candidates
    suitable.sort(key=lambda e:(-len(e['programmes']),source_key(e)))
    best = suitable[0]
    if len(suitable)>1 and not all(agree(best,e) for e in suitable[1:]):
        rejections['quality_matched_but_schedules_disagree'] += 1
        return result,method,candidates
    # The V3.5 recorder has already logged the rejection; update that record.
    record = v36.v35.records[cid]
    record.pop('reason',None)
    record.pop('candidates',None)
    record.update(status='matched',method='duplicate_resolved',epg_id=v36.safe(best['id']),source=v36.source_name(best['source']))
    resolutions.append({'channel_id':cid,'name':record['name'],'epg_id':record['epg_id'],'source':record['source'],'quality':q,'method':'explicit_quality' if len(suitable)==1 else 'quality_and_schedule_agreement'})
    return best,'duplicate_resolved',[]

engine.match_channel = match_channel

def save_epg(root):
    records = list(v36.v35.records.values())
    matched = {str(r['channel_id']):{'epg_id':r['epg_id'],'source':v36.source_name(r['source'])} for r in records if r['status']=='matched'}
    old = baseline['matches']
    gained = sorted(matched.keys()-old.keys())
    lost = sorted(old.keys()-matched.keys())
    changed = [k for k in sorted(old.keys() & matched.keys()) if old[k]!=matched[k]]
    if len(matched)!=len(root.findall('channel')):
        raise RuntimeError('XML and diagnostic counts disagree')
    REPORT.mkdir(exist_ok=True)
    review = v36.suggestions(records)
    report = dict(version='3.7.1',test_mode=True,matched_channels=len(matched),baseline_channels=len(old),programmes=len(root.findall('programme')),total_records=len(records),distinct_identities=len({(x['source'],x['epg_id']) for x in matched.values()}),gained=gained,lost=lost,changed=changed,retained=len(old.keys() & matched.keys()),resolutions=resolutions,baseline_restorations=baseline_restorations,changed_details=[dict(channel_id=k,old=old[k],new=matched[k]) for k in changed],rejections=dict(rejections),match_records=records)
    (REPORT/'v37-diagnostics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    v36.write_csv('v37-resolved.csv',resolutions,['channel_id','name','epg_id','source','quality','method'])
    v36.write_csv('v37-review-candidates.csv',review,['channel_id','name','region','language_hint','epg_id','source','candidate_region','score','same_region','review_only'])
    v36.write_csv('v37-source-catalogue.csv',v36.catalogue,['epg_id','source','region','names','keys','event','programmes'])
    print('\n===== V3.7.1 DEVELOPMENT RESULTS =====')
    print('Matched:',len(matched),'Programmes:',report['programmes'],'Resolved:',len(resolutions))
    print('Rejections:',dict(rejections))
    print('\n===== V3.7.1 REGRESSION ANALYSIS =====')
    print('Gained:',len(gained),'Lost:',len(lost),'Changed:',len(changed),'Retained:',report['retained'])
    print('Baseline restorations:', len(baseline_restorations))
    for item in baseline_restorations:
        print('Restored:', json.dumps(item, ensure_ascii=False))
    names = {str(r['channel_id']): r['name'] for r in records}
    for k in changed:
        print('Changed:', k, names.get(k, ''), old[k], '->', matched[k])
    for k in lost:
        print('Lost:', k, names.get(k, ''), old[k])
    engine.TEST_MODE = True
    if lost or changed:
        raise RuntimeError('Regression gate failed; review diagnostics. Production not modified.')
    v36.v35.original_save(root)
    print('PRODUCTION EPG NOT MODIFIED.')

engine.save_epg = save_epg

if __name__ == '__main__':
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    reviewed = json.loads(REVIEW.read_text(encoding='utf-8'))['channels']
    if baseline.get('version')!='3.6' or len(baseline['matches'])!=645:
        raise ValueError('Invalid V3.6 baseline')
    print('V3.7.1 DEVELOPMENT ONLY; reviewed IDs:',len(reviewed))
    engine.main()
