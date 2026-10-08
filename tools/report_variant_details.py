"""Review the version list ("Moottori / käyttövoima") for near-duplicate options.

Read-only: drops the disambiguating ``[CO₂ …; veromassa …]`` suffix the builder appended
to a variant (still present in the committed shards) and regroups those shards by the
label the picker then shows (brand / model / fuel / variant / years / vehicle type).
Every group with more than one row is a set of options that read almost identically —
they are exactly the rows that collapse into one option once the suffix is dropped.

    python3 tools/report_variant_details.py                  # the largest groups first
    python3 tools/report_variant_details.py --brand Volvo
    python3 tools/report_variant_details.py --limit 20
    python3 tools/report_variant_details.py --csv /tmp/variant_details.csv
    python3 tools/report_variant_details.py --check          # exit 1 while "[" suffixes exist
"""

import argparse
import csv
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_traficom_catalog as base  # noqa: E402

CALCULATION_FIELDS = set(base.CALCULATION_FIELDS)
IGNORED_FIELDS = {'id', 'source_records'}


def core_variant(variant):
    """The variant as the picker shows it: the legacy `[…]` suffix dropped."""
    return base.strip_variant_detail(variant)


def label_of(row):
    return (
        row.get('brand') or '',
        row.get('model') or '',
        row.get('powertrain') or '',
        core_variant(row.get('variant')),
        row.get('years') or '',
        row.get('vehicle_type') or '',
    )


def collect():
    groups = defaultdict(list)
    registrations = 0
    with_details = 0
    for shard in sorted(base.OUT_SHARDS.glob('*.json.gz')):
        with gzip.open(shard, 'rt', encoding='utf-8') as source:
            for row in json.load(source):
                registrations += int(row.get('registered_count') or 0)
                if base.VARIANT_DETAIL_RE.search(str(row.get('variant') or '')):
                    with_details += 1
                groups[label_of(row)].append(row)
    return groups, registrations, with_details


def differing_fields(rows):
    """Calculation fields whose value is not the same for every row of a group."""
    changed = []
    for field in base.CALCULATION_FIELDS:
        values = {json.dumps(row.get(field), sort_keys=True, ensure_ascii=False) for row in rows}
        if len(values) > 1:
            changed.append(field)
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--brand', help='only this make (case-insensitive)')
    parser.add_argument('--limit', type=int, help='only the first N groups')
    parser.add_argument('--all', action='store_true', help='list every group, not only duplicates')
    parser.add_argument('--check', action='store_true', help='exit non-zero while "[" suffixes exist')
    parser.add_argument('--csv', metavar='PATH', help='also write the groups as CSV')
    args = parser.parse_args()

    groups, registrations, with_details = collect()
    rows_total = sum(len(rows) for rows in groups.values())
    groups = {key: rows for key, rows in groups.items() if len(rows) > 1} if not args.all else groups
    if args.brand:
        needle = args.brand.casefold()
        groups = {key: rows for key, rows in groups.items() if key[0].casefold() == needle}
    duplicates = {key: rows for key, rows in groups.items() if len(rows) > 1}

    print(f'rows total                : {rows_total:,}')
    print(f'rows carrying "[…]"       : {with_details:,}')
    print(f'labels after dropping "[…]": {rows_total - sum(len(rows) - 1 for rows in duplicates.values()):,}'
          f'  (groups with >1 row: {len(duplicates):,})')
    print(f'registrations             : {registrations:,} (merging keeps this total)')
    if duplicates:
        sizes = Counter(len(rows) for rows in duplicates.values())
        print('group sizes               : ' + ', '.join(f'{size}->{count:,}' for size, count in sorted(sizes.items())))
        field_counts = Counter()
        for rows in duplicates.values():
            for field in differing_fields(rows):
                field_counts[field] += 1
        if field_counts:
            print('fields differing in groups: ' + ', '.join(
                f'{field}={count:,}' for field, count in field_counts.most_common()
            ))
        print(f'rows removed by merging   : {sum(len(rows) - 1 for rows in duplicates.values()):,}')

    ordered = sorted(
        groups.items(), key=lambda item: (-len(item[1]), item[0][0].casefold(), item[0][1].casefold())
    )
    if args.limit:
        ordered = ordered[:args.limit]

    print(f'\n{"rows":>5}  make / model / fuel / variant / years / type  [differing fields]')
    for key, rows in ordered:
        changed = differing_fields(rows)
        description = '(identical)' if not changed else '; '.join(changed)
        print(f'{len(rows):5d}  {" / ".join(key)}  [{description}]')

    if args.csv:
        with open(args.csv, 'w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['rows', 'brand', 'model', 'powertrain', 'variant', 'years', 'vehicle_type', 'differing_fields'])
            for key, rows in ordered:
                writer.writerow([len(rows), *key, '; '.join(differing_fields(rows))])
        print(f'\nWrote {args.csv}')

    if args.check and with_details:
        print(f'\nWARNING: {with_details:,} variants still carry a "[…]" suffix; the picker shows them as repeated options.')
        sys.exit(1)
    if args.check:
        print('\nNo variant carries a "[…]" suffix: every option in the version list is unique.')


if __name__ == '__main__':
    main()
