"""Re-apply catalogue normalization to the committed shards.

Use this when ``normalize_catalog()``/``build_brand_resolver()`` changes and the
raw Traficom export is not available in ``/tmp``. It loads the existing shards,
runs the standard normalization + validation and rewrites ``data/``, ``dist/``
and the index through ``write_catalog()``. Pass ``--dry-run`` to only report the
impact (brand/model collapse counts) without touching any file.

    python3 tools/renormalize_catalog.py --dry-run
    python3 tools/renormalize_catalog.py
"""

import argparse
import gzip
import json
import sys
from collections import Counter

import build_traficom_catalog as base


def load_items():
    items = []
    for path in sorted(base.OUT_SHARDS.glob('*.json.gz')):
        with gzip.open(path, 'rt', encoding='utf-8') as source:
            items.extend(json.load(source))
    return items


def malli_hide_reasons(items, selectable):
    """Count, per (brand, model) pair, why the Malli picker does not offer it."""
    brand_registrations = Counter()
    model_registrations = Counter()
    configurations = Counter()
    model_newest = {}
    for item in items:
        key = (item['brand'], item['model'])
        count = int(item.get('registered_count', 0) or 0)
        brand_registrations[item['brand']] += count
        model_registrations[key] += count
        configurations[key] += 1
        _, end = base.model_year_span(item.get('years', ''))
        if end is not None and end > model_newest.get(key, 0):
            model_newest[key] = end

    offered = {(brand, model) for brand, model, _ in selectable}
    remaining = {key for key in model_registrations if key not in offered}
    designated = Counter()
    for item in items:
        key = (item['brand'], item['model'])
        if key in remaining and base.model_is_designation(item['model'], item.get('variant', '')):
            designated[key] += 1

    reasons = Counter()
    for key in remaining:
        reason = base.model_hide_reason(
            key[0], key[1], brand_registrations[key[0]], model_registrations[key], model_newest.get(key)
        )
        if not reason and configurations[key] == designated[key]:
            reason = 'designation'
        reasons[reason or 'other'] += 1
    return reasons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='report only, write nothing')
    args = parser.parse_args()

    items = load_items()
    if not items:
        sys.exit('No shards found; nothing to normalize.')

    total_before = sum(int(item.get('registered_count', 0)) for item in items)
    brands_before = {item['brand'] for item in items}
    models_before = {(item['brand'], item['model']) for item in items}

    # Resolve the brand mapping from a tiny per-brand stub so the full catalogue
    # is not copied just to report merges.
    brand_totals = Counter()
    for item in items:
        brand_totals[item['brand']] += int(item.get('registered_count', 0))
    brand_stub = [
        {'brand': base.normalize_brand_name(brand), 'registered_count': count}
        for brand, count in brand_totals.items()
    ]
    resolve_brand = base.build_brand_resolver(brand_stub)
    brand_map = {}
    for entry in brand_stub:
        target = resolve_brand(entry['brand'])
        if target != entry['brand']:
            brand_map.setdefault(entry['brand'], set()).add(target)

    normalized = base.normalize_catalog(items)
    total_after = sum(int(item.get('registered_count', 0)) for item in normalized)
    if total_after != total_before:
        sys.exit(f'Registration total changed ({total_before:,} -> {total_after:,}); aborting.')
    base.validate_catalog(normalized)
    brands_after = {item['brand'] for item in normalized}
    selectable = base.selectable_models(normalized)
    models_after = {(brand, model) for brand, model, _ in selectable}
    hidden = malli_hide_reasons(normalized, selectable)

    print(f'Configurations:  {len(items):,} -> {len(normalized):,}')
    print(f'Registrations:   {total_before:,} -> {total_after:,}')
    print(f'Brands (Merkki): {len(brands_before):,} -> {len(brands_after):,}')
    print(f'Models (Malli):  {len(models_before):,} -> {len(models_after):,} pairs, {len(selectable):,} index rows')
    if hidden:
        print('Hidden from Malli: ' + ', '.join(f'{name}={count:,}' for name, count in sorted(hidden.items())))
    if brand_map:
        print('\nMerkki collapses:')
        for source in sorted(brand_map):
            print(f'  {source:30} -> {", ".join(sorted(brand_map[source]))}')

    if args.dry_run:
        print('\nDry run: no files written.')
        return

    base.write_catalog(normalized, normalize=False)
    print('\nWrote data/ + dist/ shards and the index via write_catalog().')


if __name__ == '__main__':
    main()
