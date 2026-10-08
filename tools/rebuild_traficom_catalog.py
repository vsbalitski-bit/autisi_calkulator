"""Rebuild bundled catalogue shards from the generated catalogue snapshot.

Use this when the original Traficom source ZIP is unavailable but the checked-in
catalogue shards need normalization, classification, and deduplication.
"""

import gzip
import json

from build_traficom_catalog import OUT_SHARDS, write_catalog


def main():
    items = []
    for path in sorted(OUT_SHARDS.glob('*.json.gz')):
        with gzip.open(path, 'rt', encoding='utf-8') as source:
            items.extend(json.load(source))
    if not items:
        raise SystemExit('The generated catalogue shards are missing.')

    write_catalog(items)
    print(f'Rebuilt catalogue from {len(items):,} existing entries')


if __name__ == '__main__':
    main()