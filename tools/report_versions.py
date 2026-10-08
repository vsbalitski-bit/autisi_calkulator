"""Review the version list ("Moottori / käyttövoima") for duplicate options.

Read-only: groups the committed shards by the label the picker shows
(``fuel · variant · body · years``, with the type-approval code stripped the same way the
browser strips it) and reports every group that still holds more than one configuration —
i.e. the duplicates a user would see — together with the fields that differ inside the group.
``--by-type`` adds the vehicle type to the label, which is what separates otherwise
identical rows when the type filter is "Ei väliä".

    python3 tools/report_versions.py                 # duplicate groups only, largest first
    python3 tools/report_versions.py --all           # every group, largest first
    python3 tools/report_versions.py --brand Volvo
    python3 tools/report_versions.py --limit 20
    python3 tools/report_versions.py --check         # exit 1 when duplicates exist
    python3 tools/report_versions.py --csv /tmp/versions.csv
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

# Fields whose difference changes what the calculator shows or computes.
CALCULATION_FIELDS = set(base.CALCULATION_FIELDS)
IGNORED_FIELDS = {'id', 'source_records'}


def label_of(row, by_type):
    key = (
        row.get('brand') or '',
        row.get('model') or '',
        row.get('powertrain') or '',
        base.visible_variant(row.get('variant'), row.get('type_approval')),
        base.visible_body(row.get('body_type')),
        row.get('years') or '',
    )
    return key + ((row.get('vehicle_type') or ''),) if by_type else key


def collect(by_type):
    groups = defaultdict(list)
    registrations = 0
    for shard in sorted(base.OUT_SHARDS.glob('*.json.gz')):
        with gzip.open(shard, 'rt', encoding='utf-8') as source:
            for row in json.load(source):
                registrations += int(row.get('registered_count') or 0)
                groups[label_of(row, by_type)].append(row)
    return groups, registrations


def differing_fields(rows):
    """Fields whose value is not the same for every row of a group."""
    changed = set()
    for field in set().union(*(row.keys() for row in rows)):
        if field in IGNORED_FIELDS:
            continue
        values = {json.dumps(row.get(field), sort_keys=True, ensure_ascii=False) for row in rows}
        if len(values) > 1:
            changed.add(field)
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', help='list every group, not only duplicates')
    parser.add_argument('--by-type', action='store_true', help='include the vehicle type in the label')
    parser.add_argument('--brand', help='only this make (case-insensitive)')
    parser.add_argument('--limit', type=int, help='only the first N groups')
    parser.add_argument('--check', action='store_true', help='exit non-zero when duplicates exist')
    parser.add_argument('--csv', metavar='PATH', help='also write the groups as CSV')
    args = parser.parse_args()

    groups, registrations = collect(args.by_type)
    rows_total = sum(len(rows) for rows in groups.values())
    duplicates = {key: rows for key, rows in groups.items() if len(rows) > 1}
    if args.brand:
        needle = args.brand.casefold()
        groups = {key: rows for key, rows in groups.items() if key[0].casefold() == needle}
        duplicates = {key: rows for key, rows in duplicates.items() if key[0].casefold() == needle}

    entries = groups if args.all else duplicates
    ordered = sorted(entries.items(), key=lambda item: (-len(item[1]), item[0][0].casefold(), item[0][1].casefold()))
    if args.limit:
        ordered = ordered[:args.limit]

    field_counts = Counter()
    for key, rows in ordered:
        for field in differing_fields(rows):
            field_counts[field] += 1

    print(f'{"rows":>5}  make / model / fuel / variant / years  [differing fields]')
    for key, rows in ordered:
        changed = differing_fields(rows)
        if not changed:
            description = '(all fields identical)'
        else:
            description = '; '.join(
                f'{field}{"*" if field in CALCULATION_FIELDS else ""}' for field in sorted(changed)
            )
        print(f'{len(rows):5d}  {" / ".join(key)}  [{description}]')

    print(
        f'\nconfigurations: {rows_total:,}, label groups: {len(groups):,}, '
        f'duplicate groups: {len(duplicates):,}, rows in them: {sum(len(rows) for rows in duplicates.values()):,}'
    )
    print(f'registrations: {registrations:,} (merging duplicates keeps this total)')
    if not args.by_type:
        print('* = calculation-relevant field; the builder merges every row that reads the same, '
              'so a duplicate group here is a real repeat in the picker')
    if field_counts:
        print('fields differing inside the listed groups: ' + ', '.join(
            f'{field}={count}' for field, count in sorted(field_counts.items())
        ))
    if duplicates:
        print(f'\nWARNING: {len(duplicates):,} duplicate label groups; the picker shows these as repeated entries.')
    else:
        print('\nNo duplicate label groups: every option in the version list is unique.')

    if args.csv:
        with open(args.csv, 'w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['rows', 'brand', 'model', 'powertrain', 'variant', 'body', 'years', 'vehicle_type', 'differing_fields'])
            for key, rows in ordered:
                label = list(key) + [''] * (7 - len(key))
                writer.writerow([len(rows), *label, '; '.join(sorted(differing_fields(rows)))])
        print(f'Wrote {args.csv}')

    if args.check and duplicates:
        sys.exit(1)


if __name__ == '__main__':
    main()
