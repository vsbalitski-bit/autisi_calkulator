"""Generate the 2026 Finnish passenger-car CO2 base-tax tables for the browser.

Download the official Traficom vehicle-tax page to /tmp/autosi-traficom-tax-2026.html
before running this builder. The generated file contains only public statutory
tax values (€/365 days), not personal vehicle data.
"""

import html
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('/tmp/autosi-traficom-tax-2026.html')
OUT = ROOT / 'assets' / 'js' / 'tax-2026.js'


def value(cell):
    return html.unescape(re.sub(r'<[^>]+>', '', cell)).strip().replace('\xa0', ' ')


def table_values(document, heading):
    start = document.index(heading)
    table_start = document.index('<table>', start)
    table_end = document.index('</table>', table_start)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', document[table_start:table_end], re.S)
    rates = {}
    for row in rows:
        cells = [value(cell) for cell in re.findall(r'<(?:td|th)[^>]*>(.*?)</(?:td|th)>', row, re.S)]
        if len(cells) != 6 or not cells[0].isdigit():
            continue
        for gram, annual in ((cells[0], cells[2]), (cells[3], cells[5])):
            gram = '400' if gram.startswith('400') else gram
            if gram.isdigit() and annual:
                rates[int(gram)] = float(annual.replace(',', '.'))
    if len(rates) != 401 or set(rates) != set(range(401)):
        raise ValueError(f'{heading}: expected rates for 0–400 g/km, got {len(rates)}')
    return [rates[index] for index in range(401)]


def main():
    if not SOURCE.exists():
        sys.exit(f'Missing {SOURCE}')
    document = SOURCE.read_text(encoding='utf-8')
    tables = {
        'wltp': table_values(document, 'Basic tax based on the CO2 emissions data using the WLTP measurement method starting from 1 January 2026'),
        'nedc': table_values(document, 'Basic tax based on the CO2 emissions data using the NEDC measurement method starting from 1 January 2026'),
    }
    payload = repr(tables).replace("'", '"').replace(' ', '')
    OUT.write_text(
        '/* Generated from Traficom vehicle-tax tables, valid from 1 January 2026. */\n'
        f'window.AutosiKululaskuriTax2026=Object.freeze({payload});\n',
        encoding='utf-8',
    )
    print(f'Wrote {OUT}')


if __name__ == '__main__':
    main()
