"""Enrich the Traficom catalogue with official EEA WLTP consumption values.

EEA's CO2Emission dataset covers EU new registrations, so historical Finnish
variants can legitimately remain unmatched. The script preserves that fact in
each record's `consumption_source` field instead of inventing official values.
"""

import gzip
import io
import json
import re
import time
import urllib.parse
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

import build_traficom_catalog as base

SHARD_DIR = base.OUT_SHARDS
DIST_SHARD_DIR = base.DIST_DATA / base.OUT_SHARDS.name
ENDPOINT = 'https://discodata.eea.europa.eu/sql'
CHUNK_SIZE = 25
CACHE_FILE = Path('/tmp/traficom_eea_cache_2026.jsonl')


def canonical(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())


def load_shard(path):
    with gzip.open(path, 'rt', encoding='utf-8') as source:
        return json.load(source)


def write_shard(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding='utf-8') as output:
                json.dump(items, output, ensure_ascii=False, separators=(',', ':'))


def load_cache():
    completed = set()
    by_approval = defaultdict(list)
    candidate_count = 0
    if not CACHE_FILE.exists():
        return completed, by_approval, candidate_count
    with CACHE_FILE.open(encoding='utf-8') as cache:
        for line in cache:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            completed.update(record.get('approvals', []))
            candidates = record.get('candidates', [])
            candidate_count += len(candidates)
            for candidate in candidates:
                by_approval[str(candidate['TAN']).upper()].append(candidate)
    return completed, by_approval, candidate_count


def save_cache(approvals, candidates):
    with CACHE_FILE.open('a', encoding='utf-8') as cache:
        cache.write(json.dumps({'approvals': approvals, 'candidates': candidates}, separators=(',', ':')) + '\n')


def query_eea(approvals):
    quoted = ', '.join("'" + approval.replace("'", "''") + "'" for approval in approvals)
    query = (
        'SELECT DISTINCT TAN AS TAN, Va, Ve, Mk, Cn, Ft, Fc, [Z (Wh/km)], '
        '[Ewltp (g/km)], [M (kg)], [Ep (KW)], Year '
        'FROM [CO2Emission].[latest].[co2cars] '
        "WHERE MS = 'FI' AND TAN IN (" + quoted + ')'
    )
    params = urllib.parse.urlencode({'query': query, 'p': 1, 'nrOfHits': 10000})
    request = urllib.request.Request(ENDPOINT + '?' + params, headers={'User-Agent': 'Autosi-Kululaskuri/0.1'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                response_data = json.load(response)
            break
        except urllib.error.HTTPError as error:
            if error.code == 404 and len(approvals) > 1:
                midpoint = len(approvals) // 2
                return query_eea(approvals[:midpoint]) + query_eea(approvals[midpoint:])
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(2 ** attempt)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 2:
                if len(approvals) > 1:
                    midpoint = len(approvals) // 2
                    return query_eea(approvals[:midpoint]) + query_eea(approvals[midpoint:])
                raise error
            time.sleep(2 ** attempt)
    if response_data.get('errors'):
        raise RuntimeError(response_data['errors'])
    return response_data.get('results', [])


def candidate_score(item, candidate):
    score = 0
    variant, version = canonical(item.get('variant_code')), canonical(item.get('version_code'))
    source_variant, source_version = canonical(candidate.get('Va')), canonical(candidate.get('Ve'))
    if variant and source_variant:
        score += 0 if variant == source_variant else 25
    if version and source_version:
        score += 0 if version == source_version else 50
    if item.get('co2') and candidate.get('Ewltp (g/km)'):
        score += min(100, abs(float(item['co2']) - float(candidate['Ewltp (g/km)'])))
    if candidate.get('Ep (KW)'):
        power = re.search(r', ([\d.]+) kW', item.get('variant', ''))
        if power:
            score += min(100, abs(float(power.group(1)) - float(candidate['Ep (KW)'])))
    return score


def item_approvals(item):
    """Every type approval a merged catalogue row can match against: the top-level
    approval plus the ones preserved in `source_records`."""
    approvals = []
    seen = set()
    for value in [(item.get('type_approval') or '').strip().upper()] + [
        (record.get('type_approval') or '').strip().upper()
        for record in (item.get('source_records') or [])
    ]:
        if value and value not in seen:
            seen.add(value)
            approvals.append(value)
    return approvals


def main():
    matched = 0
    total = 0
    queried_approvals, by_approval, candidate_count = load_cache()
    for shard_path in sorted(SHARD_DIR.glob('*.json.gz')):
        items = load_shard(shard_path)
        total += len(items)
        approvals = sorted({approval for item in items for approval in item_approvals(item)})
        pending_approvals = [approval for approval in approvals if approval not in queried_approvals]
        for offset in range(0, len(pending_approvals), CHUNK_SIZE):
            approval_batch = pending_approvals[offset:offset + CHUNK_SIZE]
            candidates = query_eea(approval_batch)
            candidate_count += len(candidates)
            save_cache(approval_batch, candidates)
            for candidate in candidates:
                by_approval.setdefault(str(candidate['TAN']).upper(), []).append(candidate)
            queried_approvals.update(approval_batch)
            time.sleep(0.25)

        for item in items:
            usable = []
            for approval in item_approvals(item):
                pool = by_approval.get(approval, [])
                usable = [candidate for candidate in pool if candidate.get('Fc') is not None or candidate.get('Z (Wh/km)') is not None]
                if usable:
                    break
            if not usable:
                item['consumption_source'] = 'CO2-derived/default estimate; no matching official EEA record'
                item['service_source'] = 'Public benchmark: Traficom calculator methodology (annualised); VIN/manufacturer plan required'
                continue
            selected = min(usable, key=lambda candidate: candidate_score(item, candidate))
            if item['powertrain'] != 'electric' and selected.get('Fc') is not None:
                item['fuel_consumption'] = round(float(selected['Fc']), 1)
            if item['powertrain'] in ('electric', 'phev') and selected.get('Z (Wh/km)') is not None:
                item['electric_consumption'] = round(float(selected['Z (Wh/km)']) / 10, 1)
            item['consumption_source'] = 'EEA official WLTP data, CO2Emission/latest/co2cars'
            item['eea_year'] = selected.get('Year')
            item['eea_type_approval'] = selected.get('TAN')
            item['data_status'] = 'Traficom technical fields verified; EEA official consumption matched; service drivers estimated'
            item['service_source'] = 'Public benchmark: Traficom calculator methodology (annualised); VIN/manufacturer plan required'
            matched += 1

        write_shard(shard_path, items)
        write_shard(DIST_SHARD_DIR / shard_path.name, items)

    enriched_items = []
    for shard_path in sorted(SHARD_DIR.glob('*.json.gz')):
        enriched_items.extend(load_shard(shard_path))
    base.write_catalog(enriched_items)

    print(f'EEA consumption matched: {matched}/{total}; candidates examined: {candidate_count}')


if __name__ == '__main__':
    main()
