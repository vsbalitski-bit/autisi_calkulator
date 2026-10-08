"""Review the Malli (model) list for body-style duplicates.

Read-only: groups models inside each make by the canonical key the builder uses after
body wording is dropped (`strip_body_words()` + `model_series_key()`) and reports every
group of names that collapse into one Malli entry — the body variants a car marketplace
merges (`A3 Sportback`, `A3 Avant` -> `A3`). ``--check`` exits non-zero while a SELECTABLE
index model name still carries a body word that should have been stripped.

    python3 tools/report_model_dupes.py            # merge groups, largest first
    python3 tools/report_model_dupes.py --brand Audi
    python3 tools/report_model_dupes.py --limit 30
    python3 tools/report_model_dupes.py --check    # exit 1 when a selectable name keeps body wording
"""

import argparse
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_traficom_catalog as base  # noqa: E402


def collect():
    """{(brand, model): registrations} over the committed shards."""
    registrations = Counter()
    for shard in sorted(base.OUT_SHARDS.glob('*.json.gz')):
        with gzip.open(shard, 'rt', encoding='utf-8') as source:
            for row in json.load(source):
                registrations[(row.get('brand') or '', row.get('model') or '')] += int(
                    row.get('registered_count') or 0
                )
    return registrations


def picker_pairs():
    """(brand, model) pairs the picker index offers."""
    text = base.OUT_FILE.read_text(encoding='utf-8')
    match = re.search(r"json_decode\(\s*'(.*)'\s*,\s*true\s*\)", text, re.S)
    if not match:
        return set()
    payload = re.sub(r"\\([\\'])", r'\1', match.group(1))
    return {(entry['brand'], entry['model']) for entry in json.loads(payload)['models']}


def merge_groups(registrations):
    """Names that share one identity once body wording is dropped."""
    groups = defaultdict(set)
    for brand, model in registrations:
        key = (brand, base.model_series_key(brand, model))
        groups[key].add(model)
    return {key: names for key, names in groups.items() if len(names) > 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--brand', help='only this make (case-insensitive)')
    parser.add_argument('--limit', type=int, help='only the first N groups')
    parser.add_argument('--check', action='store_true', help='exit non-zero when a selectable name keeps body wording')
    args = parser.parse_args()

    registrations = collect()
    groups = merge_groups(registrations)
    needle = args.brand.casefold() if args.brand else None
    if needle:
        groups = {key: names for key, names in groups.items() if key[0].casefold() == needle}

    ordered = sorted(
        groups.items(),
        key=lambda item: (
            -sum(registrations[(item[0][0], name)] for name in item[1]),
            item[0][0].casefold(),
            item[0][1].casefold(),
        ),
    )
    if args.limit:
        ordered = ordered[:args.limit]

    if not args.check:
        print(f'{"regs":>8}  make / merged-names')
        for (brand, canonical), names in ordered:
            total = sum(registrations[(brand, name)] for name in names)
            print(f'{total:8d}  {brand} / {", ".join(sorted(names))} -> {canonical}')

    print(f'\nmerge groups: {len(groups):,}; rows inside them: {sum(len(names) for names in groups.values()):,}')

    # Check: any SELECTABLE index model still carries a strippable body word (should be none after rebuild).
    selectable = picker_pairs()
    noisy = sorted(
        (brand, model) for brand, model in selectable if base.strip_body_words(model) != model
    )
    if noisy:
        print(f'WARNING: {len(noisy):,} selectable model names still carry body wording:')
        for brand, model in noisy[:20]:
            print(f'  {brand} / {model!r}')
    else:
        print('No selectable model name carries strippable body wording.')

    if args.check and noisy:
        sys.exit(1)


if __name__ == '__main__':
    main()
