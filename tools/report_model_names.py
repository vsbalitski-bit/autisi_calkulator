"""Validate the Malli (model) list: engine wording and duplicate model names.

Read-only. Loads the committed shards and reports three things:

* **engine wording** — model names that still contain engine/powertrain words. The picker
  shows the version field (Moottori / käyttövoima) for the engine, and the build strips these
  words from the model identity, so after a rebuild this list must be empty.
* **merges** — groups of names that become one model once that wording is dropped
  (`RAV 4 Hybrid` -> `Rav4`).
* **prefix candidates** — inside one make, a short name that is a strict prefix of a longer one
  (`Rav` next to `RAV4`). These are curated by hand into `MODEL_TYPO_ALIASES`, because an
  automatic prefix rule would wrongly merge `SLK` into `SLK 230`.

    python3 tools/report_model_names.py             # all sections
    python3 tools/report_model_names.py --engine    # only names with engine wording
    python3 tools/report_model_names.py --merges    # only the merge groups
    python3 tools/report_model_names.py --prefixes  # only the prefix candidates
    python3 tools/report_model_names.py --brand Toyota
    python3 tools/report_model_names.py --check     # exit 1 when a SELECTABLE model name keeps engine wording
    python3 tools/report_model_names.py --csv /tmp/model-names.csv
"""

import argparse
import csv
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_traficom_catalog as base  # noqa: E402

MAX_PREFIX_GAP = 3


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
    """(brand, model) pairs the picker index offers, empty when it cannot be read."""
    text = base.OUT_FILE.read_text(encoding='utf-8')
    match = re.search(r"json_decode\(\s*'(.*)'\s*,\s*true\s*\)", text, re.S)
    if not match:
        return set()
    payload = re.sub(r"\\([\\'])", r'\1', match.group(1))
    return {(entry['brand'], entry['model']) for entry in json.loads(payload)['models']}


def engine_names(registrations):
    return sorted(
        ((brand, model), total) for (brand, model), total in registrations.items()
        if base.MODEL_ENGINE_WORDS_RE.search(model)
    )


def merge_groups(registrations):
    """Names that share one identity once the engine wording is dropped."""
    groups = defaultdict(set)
    for brand, model in registrations:
        groups[(brand, base.model_series_key(brand, model))].add(model)
    return {key: names for key, names in groups.items() if len(names) > 1}


def prefix_candidates(registrations):
    """A short model name that is a strict prefix of a longer one inside the same make."""
    by_brand = defaultdict(dict)
    for brand, model in registrations:
        by_brand[brand].setdefault(base.canonical_model_key(brand, model), model)
    candidates = []
    for brand, models in by_brand.items():
        keys = sorted(models)
        for short in keys:
            if len(short) < 2:
                continue
            for long in keys:
                gap = len(long) - len(short)
                if short != long and long.startswith(short) and 0 < gap <= MAX_PREFIX_GAP:
                    candidates.append((brand, models[short], models[long], registrations[(brand, models[short])]))
    return sorted(candidates, key=lambda row: (-row[3], row[0].casefold(), row[1].casefold()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', action='store_true', help='only names with engine wording')
    parser.add_argument('--merges', action='store_true', help='only the merge groups')
    parser.add_argument('--prefixes', action='store_true', help='only the prefix candidates')
    parser.add_argument('--brand', help='only this make (case-insensitive)')
    parser.add_argument('--limit', type=int, help='only the first N rows per section')
    parser.add_argument('--check', action='store_true', help='exit non-zero when a selectable name keeps engine wording')
    parser.add_argument('--csv', metavar='PATH', help='write the findings as CSV')
    args = parser.parse_args()

    registrations = collect()
    needle = args.brand.casefold() if args.brand else None
    engine = [
        row for row in engine_names(registrations)
        if not needle or row[0][0].casefold() == needle
    ]
    merges = {
        key: names for key, names in merge_groups(registrations).items()
        if not needle or key[0].casefold() == needle
    }
    prefixes = [
        row for row in prefix_candidates(registrations)
        if not needle or row[0].casefold() == needle
    ]
    if args.limit:
        engine = engine[:args.limit]
        prefixes = prefixes[:args.limit]

    show_all = not (args.engine or args.merges or args.prefixes)
    picker = picker_pairs()
    if show_all or args.engine:
        selectable = [row for row in engine if row[0] in picker]
        print(f'--- model names with engine wording: {len(engine)} '
              f'({len(selectable)} of them selectable in the Malli index) ---')
        for (brand, model), total in (engine if show_all else selectable[:40]):
            marker = 'in picker' if (brand, model) in picker else 'hidden'
            print(f'{total:9d}  {brand} / {model}  [{marker}]')
        if not show_all and len(selectable) > 40:
            print(f'  … {len(selectable) - 40} more (use --limit or --csv)')
    if show_all or args.merges:
        merged_names = sum(len(names) - 1 for names in merges.values())
        print(f'\n--- groups that merge once engine wording is dropped: {len(merges)} '
              f'({merged_names} names removed) ---')
        for key, names in sorted(merges.items(), key=lambda item: -len(item[1]))[:25]:
            print(f'{len(names):4d}  {key[0]} -> {", ".join(sorted(names))}')
    if show_all or args.prefixes:
        print(f'\n--- prefix candidates to curate ({len(prefixes)}) ---')
        for brand, short, long, total in prefixes[:40]:
            print(f'{total:9d}  {brand}: {short!r} -> {long!r} (+{len(long) - len(short)})')

    print(
        f'\nmodels: {len(registrations):,} (make, model) pairs, '
        f'{len(merges):,} merge groups, {len(engine):,} names with engine wording, '
        f'{len(prefixes):,} prefix candidates'
    )
    if args.check:
        # The gate mirrors validate_index(): only names the picker OFFERS must be engine-free.
        selectable = [row for row in engine if row[0] in picker]
        if selectable:
            print(
                f'FAIL: {len(selectable):,} selectable model names still carry engine wording '
                '(the Malli list must show the model only).'
            )
            sys.exit(1)
        hidden = len(engine) - len(selectable)
        note = (
            f' ({hidden:,} hidden shard name(s) kept and classified as unknown)'
            if hidden else ''
        )
        print(f'OK: no selectable model name carries engine wording{note}.')

    if args.csv:
        with open(args.csv, 'w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['section', 'brand', 'name', 'target', 'registrations'])
            for (brand, model), total in engine:
                writer.writerow(['engine', brand, model, '', total])
            for (brand, _), names in sorted(merges.items()):
                for name in sorted(names):
                    writer.writerow(['merge', brand, name, '', registrations[(brand, name)]])
            for brand, short, long, total in prefixes:
                writer.writerow(['prefix', brand, short, long, total])
        print(f'Wrote {args.csv}')


if __name__ == '__main__':
    main()
