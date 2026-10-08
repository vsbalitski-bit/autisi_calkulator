"""Review the version list ("Moottori / käyttövoima") for leftover technical noise.

Read-only: loads the committed shards and reports how many variant labels still carry the
noise the builder strips (`clean_variant()`): door counts, body-style words/codes, cm3
displacement and type-approval code tails. ``--check`` exits non-zero while any noise
remains, mirroring the guard in `validate_catalog()`.

    python3 tools/report_variant_noise.py           # summary + examples
    python3 tools/report_variant_noise.py --limit 30
    python3 tools/report_variant_noise.py --check   # exit 1 while noise remains
"""

import argparse
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_traficom_catalog as base  # noqa: E402

# Only the high-confidence, always-stripped tokens are treated as noise: these must never
# appear in a selectable variant because `clean_variant()` removes them before the merge.
NOISE_PATTERNS = (
    ('door', base.VARIANT_DOOR_RE),
    ('cm3', base.VARIANT_CM3_RE),
    ('body-code', base.VARIANT_BODY_CODE_RE),
    ('body-word', base.VARIANT_BODY_WORD_RE),
    ('code-tail', base.VARIANT_CODE_TAIL_RE),
)


def collect():
    counts = Counter()
    samples = {name: [] for name, _ in NOISE_PATTERNS}
    total = 0
    for shard in sorted(base.OUT_SHARDS.glob('*.json.gz')):
        with gzip.open(shard, 'rt', encoding='utf-8') as source:
            for row in json.load(source):
                total += 1
                variant = row.get('variant') or ''
                for name, pattern in NOISE_PATTERNS:
                    if pattern.search(variant):
                        counts[name] += 1
                        if len(samples[name]) < 6:
                            samples[name].append(variant)
    return total, counts, samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=0, help='show up to N example labels per pattern')
    parser.add_argument('--check', action='store_true', help='exit non-zero while noise remains')
    args = parser.parse_args()

    total, counts, samples = collect()
    print(f'rows: {total:,}')
    for name, _ in NOISE_PATTERNS:
        number = counts[name]
        print(f'  {name:10s}: {number:,} ({100 * number / total:.2f}%)')
        for variant in samples[name][:args.limit]:
            print(f'      {variant!r}')
    if any(counts.values()):
        print(f'\nWARNING: {sum(counts.values()):,} variant labels still carry technical noise.')
    else:
        print('\nNo technical noise: every variant label is clean.')
    if args.check and any(counts.values()):
        sys.exit(1)


if __name__ == '__main__':
    main()
