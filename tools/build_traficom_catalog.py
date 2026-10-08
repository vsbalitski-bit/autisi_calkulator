"""Build the catalogue of unique passenger-car configurations from Traficom.

Inputs are deliberately outside the repository because the vehicle register is
large. Download the official vehicle file to /tmp before running this script:

    traficom_vehicles_2026.zip

The output only retains aggregate technical characteristics. It does not retain
registration marks, VINs, municipality, or odometer readings.
"""

import csv
import fcntl
import gzip
import hashlib
import json
import os
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from io import TextIOWrapper
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VEHICLES_FILE = Path('/tmp/traficom_vehicles_2026.zip')
OUT_FILE = ROOT / 'data' / 'traficom-catalog-2026.php'
OUT_SHARDS = ROOT / 'data' / 'traficom-catalog-2026'
DIST_DATA = ROOT / 'dist' / 'autosi-kululaskuri' / 'data'
BUILD_LOCK_PATH = Path('/tmp/traficom_catalog_build.lock')
SOURCE_DATE = '2026-06-30'


@contextmanager
def acquire_catalog_lock(lock_path=BUILD_LOCK_PATH):
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open('w', encoding='utf-8')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError(f'Catalog build already running: {lock_path}') from exc
    try:
        yield lock_path
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '').replace('\xa0', ' ')).strip()


def model_key(brand, model):
    return (clean(brand).upper(), clean(model).upper())


def vehicle_type(vehicle_class, body_type, seats=0, vehicle_group=''):
    vehicle_class = clean(vehicle_class).upper()
    body_type = clean(body_type).upper()
    group_codes = set(re.split(r'[,\s]+', clean(vehicle_group))) if clean(vehicle_group) else set()
    motorhome_groups = {'29'}
    minibus_groups = {'35'}
    bus_groups = {'37', '38', '39', '40', '41', '42', '43', '44', '45', '46', '47'}
    special_groups = {
        '23', '25', '27', '31', '32', '33', '36', '48', '50', '51', '52', '53',
        '54', '55', '57', '58', '59', '60', '62', '63', '64', '65', '66', '67',
        '68', '69', '70',
    }
    special_bodies = {'SB', 'SC', 'SD', 'SF', 'SG', 'SH', 'SL', 'SM'}
    bus_bodies = {
        'CA', 'CB', 'CC', 'CD', 'CE', 'CF', 'CG', 'CH', 'CI', 'CJ', 'CK', 'CL',
        'CM', 'CN', 'CO', 'CP', 'CQ', 'CR', 'CS', 'CT', 'CU', 'CV', 'CW', 'CX',
    }
    if group_codes & motorhome_groups or body_type == 'SA':
        return 'motorhome'
    if vehicle_class in {'M2', 'M2G'} or group_codes & minibus_groups:
        return 'minibus'
    if vehicle_class in {'M3', 'M3G'} or group_codes & bus_groups or body_type in bus_bodies:
        return 'bus'
    if group_codes & special_groups or body_type in special_bodies:
        return 'special'
    if vehicle_class in {'N1', 'N1G'}:
        if body_type == 'BB':
            return 'van'
        if body_type == 'BE':
            return 'pickup'
        return 'light_truck'
    if body_type == 'BB':
        return 'van'
    if body_type in {'BA', 'BE'}:
        return 'pickup'
    return 'passenger'


def canonical_brand_key(brand):
    normalized = unicodedata.normalize('NFKC', clean(brand)).casefold()
    return re.sub(r'[\W_]+', ' ', normalized, flags=re.UNICODE).strip()


def make_token(brand):
    return re.split(r'[,\s\-/–]+', clean(brand), 1)[0]


BRAND_ALIASES = (
    (re.compile(r'(?i)(?<![0-9a-z])m[\s.\-]*b(?![0-9a-z])'), 'Mercedes-Benz'),
    (re.compile(r'(?i)\bmercedes[\s\-]+benz\b'), 'Mercedes-Benz'),
    (re.compile(r'(?i)\bmercedes\b(?![\s\-]*benz)'), 'Mercedes-Benz'),
    (re.compile(r'(?i)(?<![0-9a-z])vw(?![0-9a-z])'), 'Volkswagen'),
)

# Abbreviations of a make that Traficom also writes INSIDE the model text (`VW PASSAT`,
# `MB C 220`, `M-B E200`). Keyed by the canonical make. Used by `strip_make_alias_prefix()`
# and by `model_is_unknown()`, and applied only when the row's own make resolves to that
# make — a converter naming its chassis (`Acbus / MB Sprinter`) keeps the reference and
# BMW's `M 550d` is never touched.
MODEL_MAKE_ALIAS_PREFIXES = {
    'Mercedes-Benz': ('Mercedes-Benz', 'Mercedes Benz', 'Mercedesbenz', 'Mercedes', 'M-B', 'M.B.', 'MB'),
    'Volkswagen': ('Volkswagen', 'VW'),
}

BRAND_SUFFIXES = (
    'gmbh & co. kg', 'gmbh & co kg', 'gmbh & co', 'gmbh', 'd.o.o.', 'd.o.o', 'd.o.o',
    'limited', 'ltd', 's.p.a.', 's.p.a', 's.r.l.', 's.r.l', 's.r.o.', 's.r.o', 'srl',
    'spa', 'inc', 'a/s', 'a.s.', 'b.v.', 'nv', 'bv', 'plc', 'corporation', 'corp',
    'company limited', 'company', 'oyj', 'oy', 'ab', 'ag', 'sa', 'kg', 'o.o.', 's.coop',
)

# Hand-curated corrections for misspellings in the human-entered Traficom make
# field. Keys are `clean(brand).casefold()`; real marques that merely look alike
# (Matra/Mazda, Fiat/Faw, Man/Mini, Aec/Amc, Fso/Fuso…) are deliberately absent.
BRAND_TYPO_ALIASES = {
    'bww': 'BMW',
    'bmw': 'BMW',
    'volswagen': 'Volkswagen',
    'hundai': 'Hyundai',
    'pösll': 'Pössl',
    'poessl': 'Pössl',
    'burstner': 'Bürstner',
    'garthago': 'Carthago',
    'studebacker': 'Studebaker',
    'pacard': 'Packard',
    'll0yd': 'Lloyd',
    'standart': 'Standard',
    'willys overla': 'Willys Overland',
    'commerce': 'Commer',
    'popeda': 'Pobeda',
    'morel': 'Morelo',
    'tricano': 'Trigano',
    'mersedes-benz its system': 'Mercedes-Benz',
    'auto-merc/mercedes-benz sprinter': 'Mercedes-Benz',
    'auto-merk/mercedes-benz sprinter': 'Mercedes-Benz',
    'arbeitsgem.volkswagen-m': 'Volkswagen',
    'saxas nutzfahr wrdau': 'Saxas Nutzfahrzeuge Werdau',
    'auwaerter, gottlob': 'Auwaerter',
    'g.auwaerter, stgt': 'Auwaerter',
    'g.auwaerter.stlt': 'Auwaerter',
    'adam opel': 'Opel',
    'peugeotduo-line': 'Peugeot',
    'salvador caetan': 'Caetano',
    'teve ford': 'Ford',
    'teve transit': 'Ford',
    'teve-volkswagen 580m': 'Volkswagen',
    'tatraplan': 'Tatra',
    'willys jeep': 'Willys',
    'willys-knight': 'Willys',
}

# Hand-curated MERGES of label variants that are one and the same make: a short form
# of a fuller marque name (`Armstrong` -> `Armstrong Siddeley`, `Graham` ->
# `Graham Paige`), a corporate/trade suffix that is not a legal form (`Karma Automotive
# Llc` -> `Karma`, `Great Wall Motor` -> `Great Wall`, `Westfalia Mobil` ->
# `Westfalia`, `Fendt-Caravan` -> `Fendt`), a composite whose base make is the marque
# (`Matra-Simca`/`Talbot-Matra` -> `Matra`), an abbreviation of the full company name
# (`London Taxis International` -> `Lti`), and model names parked in the make field
# (`Mgb`/`Mga` -> `Mg`). Keys = `clean(brand).casefold()`. Real marques that merely
# look alike (Matra/Mazda, Fiat/Faw…) are deliberately absent.
BRAND_MERGE_ALIASES = {
    'armstrong': 'Armstrong Siddeley',
    'graham': 'Graham Paige',
    'karma automotive llc': 'Karma',
    'london taxis international': 'Lti',
    'great wall motor': 'Great Wall',
    'matra-simca': 'Matra',
    'talbot-matra': 'Matra',
    'mgb': 'Mg',
    'mga': 'Mg',
    'terraplane hudson': 'Terraplane',
    'westfalia mobil': 'Westfalia',
    'fendt-caravan': 'Fendt',
}

# Data-entry placeholders that are not makes at all; kept in the shards but not
# offered in the Merkki picker.
BRAND_PLACEHOLDERS = {'ks. huom.', 'övriga', 'omavalmiste', 'v-series 60 sp'}

# Curated entries that are not a real make on their own, so they must not appear in
# the Merkki picker: composite "converter/make" values whose base make already
# exists as its own entry, country-tagged variants, model names parked in the make
# field, and component/trailer/body suppliers. Keys are `clean(brand).casefold()`.
# Verified against the 30.6.2026 snapshot with `tools/report_brands.py`. Kept in the
# shards, so the registered-vehicle total is unchanged.
HIDDEN_BRANDS = {
    # Composite "converter/make" values whose base make exists separately.
    'autocaravans rimor',                # -> Rimor
    'cms auto/mercedes-benz',            # -> Mercedes-Benz
    'cuby iveco',                        # -> Iveco
    'warmiaki/mercedes-benz sprinter',   # -> Mercedes-Benz
    'daimlerchrysler-hymer',             # -> Hymer
    'spartan fleetwood',                 # -> Fleetwood
    # Make field actually carries a model / a build artefact.
    'ac cobra shelby 427',               # -> AC
    'bl cars',                           # British Leyland build label
    # Country-tagged duplicates of an existing make.
    'magyar suzuki (h)',                 # -> Suzuki
    'santana (e)',                       # -> Santana
    # Component, trailer and body suppliers, not vehicle makes.
    'al-ko', 'palfinger', 'humbaur', 'r.m.trailers', 'kerstner',
    'pollmann', 'remetz', 'truckmasters', 'umesläp', 'carbodies',
    'edward davies commercials',
}

# A make with fewer registered vehicles than this across the whole catalogue is
# treated as a one-off / obsolete data entry and hidden from the Merkki picker
# (99 of 448 makes in the 30.6.2026 snapshot have a single registration).
# Set to 0 to disable the threshold. Tune it with `tools/report_brands.py`.
MIN_BRAND_REGISTRATIONS = 2


def brand_is_placeholder(brand):
    return clean(brand).casefold() in BRAND_PLACEHOLDERS


def brand_is_hidden(brand):
    return clean(brand).casefold() in HIDDEN_BRANDS


# A Malli entry is hidden from the picker only when it is BOTH rare and old, so that
# niche modern cars (a single Ferrari/Zeekr import) and popular classics stay
# selectable. `years` holds the first-registration years of the vehicles in stock, so
# the newest end of the span is the age signal. Set MIN_MODEL_REGISTRATIONS to 0 to
# disable the threshold. Shard data is kept either way. Tune both with
# `tools/report_models.py`.
MIN_MODEL_REGISTRATIONS = 2
MIN_MODEL_YEAR = 1990

# Powertrain codes available per make/model/vehicle type, so the picker can hide the
# makes and models that have no version for the fuel the user chose. Mirror of
# `Autosi_Kululaskuri::POWERTRAINS` in the plugin.
POWERTRAIN_CODES = ('petrol', 'diesel', 'hybrid', 'phev', 'electric')

# Curated Malli entries that must never be offered. Keys are
# `(clean(brand).casefold(), canonical_model_key(brand, model))`. Empty by default.
HIDDEN_MODELS = set()


def model_is_hidden(brand, model):
    return (clean(brand).casefold(), canonical_model_key(brand, model)) in HIDDEN_MODELS


# Hand-curated Malli corrections. Outer key = `clean(brand).casefold()`, inner key
# = canonical model key (separator/case/diacritic-insensitive), value = correct
# spelling. Legitimate trims/variants (Cooper S/D, Corsa-C, Model S/X/Y, Kadett
# B/C/D/E, LEON ST/SP/SC, GTI/GTE/GTD…) are deliberately absent.
MODEL_TYPO_ALIASES = {
    'skoda': {
        'ostavia': 'Octavia', 'oktavia': 'Octavia', 'suberb': 'Superb', 'oktaviascout': 'Octavia Scout',
    },
    'volkswagen': {
        'passt': 'Passat', 'trasporter': 'Transporter', 'transportter': 'Transporter',
        'transorter': 'Transporter', 'tranporter': 'Transporter', 'tiquan': 'Tiguan',
        'cafter': 'Crafter', 'shran': 'Sharan', 'sharon': 'Sharan', 'saharan': 'Sharan',
        'toureg': 'Touareg', 'newbeetlecapriolet': 'New Beetle Cabriolet',
        'golfgabriolet': 'Golf Cabriolet', 'kleinbuss': 'Kleinbus', 'multivanstarline': 'Multivan Startline',
    },
    'toyota': {
        'landcruicer': 'Land Cruiser', 'landgruiser': 'Land Cruiser', 'landcuiser': 'Land Cruiser',
        'higlander': 'Highlander', 'vanquard': 'Vanguard', 'rav': 'Rav4',
        'landcruiser150series9': 'Land Cruiser 150',
    },
    'ford': {
        'trasnsit': 'Transit', 'transitcuistom': 'Transit Custom', 'tranitcustom': 'Transit Custom',
        'transitconnec': 'Transit Connect', 'mustan': 'Mustang', 'mondeohydrid': 'Mondeo Hybrid',
        'aglia': 'Anglia', 'tunderbird': 'Thunderbird', 'thundebird': 'Thunderbird',
        'fairline': 'Fairlane', 'streetkaa': 'Street Ka', 'transitpostyle': 'Transit PROSTYLE',
        'rancher': 'Ranchero', 'prefekt': 'Prefect', 'modella': 'Model A',
    },
    'mercedes-benz': {
        'srinter': 'Sprinter', 'spriter': 'Sprinter', 'sprintter': 'Sprinter',
        'spriinter': 'Sprinter', 'spinter': 'Sprinter', 'vklassse': 'V-Klasse', 'vklase': 'V-Klasse',
        'vitotouren': 'Vito Tourer', 'vitotouner': 'Vito Tourer', 'vitotouer': 'Vito Tourer',
        'turismorhdl': 'Tourismo RHD-L', 'flobyflaksrinter': 'Floby Flak Sprinter',
        'flobyflacksprinter': 'Floby Flak Sprinter', 'gelendewagen': 'Geländewagen',
    },
    'mitsubishi': {
        'otlander': 'Outlander', 'outlanderphew': 'Outlander PHEV', 'pajeromonter': 'Pajero/Montero',
        'mitsubishil200': 'L200',
    },
    'kia': {'sportace': 'Sportage'},
    'renault': {
        'traffic': 'Trafic', 'mecanescenic': 'Megane Scenic', 'clioetechhydrid': 'CLIO (E-Tech Hybrid)',
    },
    'subaru': {
        'forrester': 'Forester', 'legasy': 'Legacy', 'imbreza': 'Impreza', 'lecacygtb': 'Legacy GT-B',
    },
    'citroen': {'jumby': 'Jumpy'},
    'tesla': {'modess': 'Model S'},
    'hyundai': {'ionic': 'Ioniq'},
    'peugeot': {'patner': 'Partner'},
    'suzuki': {'grantvitara': 'Grand Vitara'},
    'jeep': {'wrankler': 'Wrangler', 'grancherokee': 'Grand Cherokee'},
    'land rover': {
        'rangerrover': 'Range Rover', 'rangeroverevogue': 'Range Rover Evoque',
        'rangeroverspor': 'Range Rover Sport',
    },
    'chrysler': {'grandvoager': 'Grand Voyager', 'sepringconvertible': 'Sebring Convertible'},
    'fiat': {
        'dugato': 'Ducato', 'dublo': 'Doblo', 'defthleffs': 'Dethleffs', 'euramobiel': 'Euramobil',
        'affinitycambervan': 'AFFINITY CAMPER VAN',
    },
    'porsche': {'boxter': 'Boxster', 'boxters': 'Boxster S', 'cayannes': 'Cayenne S'},
    'scania': {'omnierpress': 'OmniExpress', 'cityewide': 'Citywide', 'inerlink': 'Interlink'},
    'dodge': {
        'challanger': 'Challenger', 'callenger': 'Challenger', 'challangerrt': 'Challenger R/T',
    },
    'honda': {'strem': 'Stream', 'legent': 'Legend'},
    'cadillac': {'escallade': 'Escalade', 'coupedewille': 'Coupe de Ville'},
    'opel': {
        'kadet': 'Kadett', 'compovan': 'Combo Van', 'recorde': 'REKORD-E', 'record': 'Rekord',
        'olympiarecord': 'Olympia Rekord', 'kadetcoupe': 'Kadett Coupe', 'astrastasionwagon': 'Astra Station Wagon',
    },
    'mg': {'marvelelectric': 'Marvel R Electric', 'marvellelectric': 'Marvel R Electric'},
    'audi': {'etronssportpack': 'e-tron S Sportback'},
    'chevrolet': {
        'corvettestingay': 'Corvette Stingray', 'corvettestringray': 'Corvette Stingray',
        'avalance': 'Avalanche', 'abache': 'Apache', 'fleetsidepickud': 'Fleetside Pick Up',
        'biscaune': 'Biscayne', 'masterdelux': 'Master Deluxe',
    },
    'mercury': {
        'coucar': 'Cougar', 'montrey': 'Monterey', 'grandmarguis': 'Grand Marquis',
        'monteclair': 'Montclair', 'cyklonegt': 'Cyclone GT',
    },
    'plymouth': {'satelite': 'Satellite'},
    'bentley': {
        'bentaygahydrid': 'Bentayga Hybrid', 'bentayagahybrid': 'Bentayga Hybrid',
        'continentagtspeed': 'Continental GT Speed',
    },
    'lincoln': {'navicator': 'Navigator', 'towncarlimosine': 'TOWN CAR Limousine'},
    'oldsmobile': {'nintyeight': 'Ninety Eight'},
    'pontiac': {'firebirtformula': 'Firebird Formula'},
    'lancia': {'deltahfintergrale': 'Delta HF Integrale'},
    'smart': {'fourtwo': 'Fortwo'},
    'saab': {'sonetiii': 'Sonett III'},
    'nissan': {
        'kingcap': 'King Cab', 'doublecap': 'Double Cab', 'navaradoblecab': 'Navara Double Cab',
        'kingcapnavara': 'KING CAB Navara',
    },
    'alfa romeo': {'breda': 'Brera'},
    'seat': {'leonsporttourerst': 'LEON SPORTOURER ST', 'leonsporttourersst': 'LEON SPORTOURER ST'},
    'mini': {'coopercaprio': 'Cooper Cabrio'},
    'alpina': {'bmwalbinab6coupeswitchtronic': 'B6 Coupe Switch-Tronic'},
    'volvo': {'volvors60': 'R + S60'},
}

# Make spellings that are glued to the model name but more than one edit away from
# the make itself, so they need hand curation (`ADRIATIK Coral S 660 SL` under the
# make `Adria`). A model that consists of such a spelling only is a make, not a model.
EXTRA_MAKE_PREFIXES = {
    'adria': ('adriatik',),
}


def model_typo_fix(brand, model):
    """Correct a hand-curated model misspelling, otherwise return the model as-is."""
    fixes = MODEL_TYPO_ALIASES.get(clean(brand).casefold())
    if not fixes:
        return model
    return fixes.get(canonical_model_key(brand, model), model)


def strip_brand_suffix(value):
    """Drop trailing legal-form and country tags (GmbH, Ltd, S.p.A, (SLO), …)."""
    value = clean(value)
    changed = True
    while changed and value:
        changed = False
        stripped = re.sub(r'(?i)[\s,;]*\([a-z]{2,4}\)\s*$', '', value)
        if stripped != value:
            value = stripped.strip(' ,;')
            changed = True
            continue
        for suffix in sorted(BRAND_SUFFIXES, key=len, reverse=True):
            stripped = re.sub(r'(?i)[\s,\-]+' + re.escape(suffix) + r'\s*\.?\s*$', '', value)
            if stripped != value and stripped.strip(' ,-.'):
                value = stripped.strip(' ,-.')
                changed = True
                break
    return value or clean(value)


def normalize_brand_name(brand):
    """Expand make abbreviations, fix known typos and strip legal-form suffixes."""
    value = clean(brand)
    typo = BRAND_TYPO_ALIASES.get(value.casefold())
    if typo:
        return typo
    merge = BRAND_MERGE_ALIASES.get(value.casefold())
    if merge:
        return merge
    for pattern, replacement in BRAND_ALIASES:
        value = pattern.sub(replacement, value)
    return strip_brand_suffix(value)


def canonical_model_key(brand, model):
    """Case/separator/diacritic-insensitive identity of a model within a brand."""
    value = normalize_model(brand, clean(model))
    decomposed = unicodedata.normalize('NFKD', value)
    folded = ''.join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r'[^0-9a-z]+', '', folded.casefold())


SERIES_WORDS_RE = re.compile(r'(?i)\b(?:sarja|sarjan|serie|series|ser|reihe|luokka|klass|class)\b')
SUPERSCRIPT = str.maketrans({'\u00b9': None, '\u00b2': None, '\u00b3': None})


def _model_norm(value):
    decomposed = unicodedata.normalize('NFKD', str(value or ''))
    folded = ''.join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r'[^0-9a-z]+', '', folded.casefold())


# Engine / powertrain wording that must not be part of a Malli name: the version field
# (Moottori / käyttövoima) already identifies the engine, while leaving the words in splits one
# car into several model entries (`RAV 4 Hybrid` next to `RAV4`). Only words that always denote
# the power source or an engine family are listed; trims and drivetrain badges that also name a
# model line (`GTI`, `Cooper S`, `quattro`, `4x4`) are deliberately kept, and digits
# (displacement, `Mazda 6`, `Peugeot 307`) are never touched. `e-tron` is NOT listed: it is
# Audi's model-line name (`e-tron`, `e-tron GT`, `e-tron 50`), not a suffix.
MODEL_ENGINE_WORDS_RE = re.compile(
    r'(?i)(?:'
    r'\b(?:tfsi|tsi|tdi|gdi|mpi)\s+e\b'          # Volkswagen/Audi plug-in marker: "TFSI e"
    r'|\b(?:hybrid|hybridi|phev|plugin[\s-]*hybrid|plug[\s-]*in(?:[\s-]*hybrid)?|lataushybridi|mild[\s-]*hybrid|'
    r'electric|elektro|sähk[öo]|bensiini|petrol|diesel|kaasu|gas|cng(?!-)|lpg(?!-)|bifuel|flexifuel|e85|'
    r'battery[\s-]*electric)\b'
    r'|\b(?:tdi|tsi|tfsi|fsi|sdi|gdi|mpi|mpfi|cdi|cdti|tdci|hdi|bluehdi|dci|crdi|jtd|multijet|d-?4-?d|'
    r'ecoboost|ecotec|vtec|vvti|multiair|twinair|e-?tech|skyactiv|puretech|thp|vti|twinturbo|'
    r'bluetec|bluetech|[ck]ompressor|komp|turbodiesel|dpf)\b'
    r')'
)


def strip_engine_words(model):
    """Remove engine/powertrain wording from a model name (never the whole name)."""
    value = MODEL_ENGINE_WORDS_RE.sub(' ', str(model or ''))
    value = re.sub(r'\(\s*\)', ' ', value)
    value = re.sub(r'\s{2,}', ' ', value)
    value = value.strip(' -,/')
    return value or str(model or '')


# Body-style wording that must not split one Malli entry into several: the picker groups
# body variants under the base model (`A3 Sportback`, `A4 Avant`, `Octavia Kombi` -> `A3`,
# `A4`, `Octavia`) the way a car marketplace does, while the version list still tells the
# body apart. Only words that always denote a body style are listed; trims (`GTI`), drivetrain
# badges (`quattro`, `4x4`) and ambiguous words that are often part of a model name (`Coupé`,
# `Sedan`, `Roadster`, `Van`, `Pickup`) are deliberately kept.
MODEL_BODY_WORDS_RE = re.compile(
    r'(?i)\b(?:'
    r'farmari|viistoper[äa]|avoauto|avolava|umpikorinen|monik[äa]ytt[öo]ajoneuvo|matkailuauto|'
    r'variant|sportback|avant|tourer|combi|kombi|estate|station\s+wagon|sports\s+tourer|'
    r'break|turnier|sw|stw|gran\s+turismo|gran\s+coupe|sport\s+turismo'
    r')\b'
)


def strip_body_words(model):
    """Remove body-style wording from a model name (never the whole name)."""
    value = MODEL_BODY_WORDS_RE.sub(' ', str(model or ''))
    value = re.sub(r'\s{2,}', ' ', value)
    value = value.strip(' -,/')
    return value or str(model or '')


# Body-style codes the version list labels (mirrors the JS `bodyLabels` map exactly).
# Codes that share a label (BA/BE) and codes without a label (buses, special-purpose,
# empty) are deliberately identical here, so they merge the way the user sees them.
BODY_LABELS = {
    'AA': 'Sedan', 'AB': 'Viistoperä', 'AC': 'Farmari', 'AD': 'Coupé',
    'AE': 'Avoauto', 'AF': 'Tila-auto', 'SA': 'Matkailuauto', 'BB': 'Pakettiauto',
    'BA': 'Avolava-auto', 'BE': 'Avolava-auto',
}


def visible_body(body_type):
    """The body text the version list shows, or '' when the code has no label."""
    return BODY_LABELS.get(clean(body_type).upper(), '')


def model_series_key(brand, model):
    """Identity of a model ignoring series/class, engine and body wording (`RAV 4 Hybrid` == `Rav4`)."""
    base = normalize_model(brand, clean(model))
    base = base.translate(SUPERSCRIPT)
    base = strip_engine_words(base)
    base = strip_body_words(base)
    base = re.sub(r'(?i)\s*\(\s*(\d{1,3})\s+series\s*\)', r' \1', base)
    base = SERIES_WORDS_RE.sub(' ', base)
    base = re.sub(r'(?i)\b(\d{1,3})er\b', r'\1', base)
    return _model_norm(re.sub(r'\s{2,}', ' ', base).strip())


def model_display(names):
    """Choose the spelling shown in the Malli list for one merged model group.

    Groups that differ by a series/class word keep the shortest well-formed base
    (3-sarja/3er Reihe -> 3); groups that differ only by case/spacing keep the
    mixed-case spelling.
    """
    variants = set(names)
    if len({_model_norm(name) for name in variants}) > 1:
        chosen = sorted(
            variants,
            key=lambda name: ('"' in name or "'" in name, len(name), name.islower(), -names[name], name.casefold()),
        )[0]
        if len(chosen) == 1 and chosen.isalpha() and chosen.islower():
            chosen = chosen.upper()
        return chosen
    return sorted(
        variants,
        key=lambda name: (
            name == name.upper() and re.search(r'[A-Za-z]', name) is not None,
            '_' in name,
            -names[name],
            len(name),
            name.casefold(),
        ),
    )[0]


def model_is_unknown(brand, model):
    """A model that only repeats the make, is a placeholder or is nothing but engine
    wording (`Electric`) is not selectable."""
    value = clean(model)
    key = re.sub(r'[^0-9a-z]+', '', unicodedata.normalize('NFKC', value).casefold())
    if not key or key in {'tuntematon', 'unknown', 'eitiedossa', 'muu', 'other'}:
        return True
    if MODEL_ENGINE_WORDS_RE.fullmatch(value):
        return True
    brand_key = re.sub(r'[^0-9a-z]+', '', unicodedata.normalize('NFKC', clean(brand)).casefold())
    alias_keys = {
        re.sub(r'[^0-9a-z]+', '', unicodedata.normalize('NFKC', alias).casefold())
        for alias in MODEL_MAKE_ALIAS_PREFIXES.get(normalize_brand_name(clean(brand)), ())
    }
    if not brand_key:
        return False
    return key in {brand_key, *alias_keys, *EXTRA_MAKE_PREFIXES.get(brand_key, ())}


# Values that are Traficom's technical `mallimerkinta` (engine/body/approval data)
# rather than a commercial model name. They appear in the Malli list only when
# `kaupallinenNimi` was empty; the engine already lives in the next field
# (variant). Pure model numbers (Mazda 6, Peugeot 307, Porsche 911) and names that
# legitimately carry an engine code (C 220 CDI, Q5 50 TFSI e, ID.4 PRO 150 kW) are
# deliberately not matched.
TECHNICAL_MODEL_RE = re.compile(
    r'(?i)'
    r'^\d+(?:[.,]\d+)?\s*(?:cdi|tdi|tsi|tdci|hdi|d-?4d|fsi|tfsi|gdi|mpi|sdi|dci|jtd|multijet)$'
    r'|\b[2-5]\s*d\b'                 # door code: 2D, 4D, 5D, 2D SEDAN
    r'|\b\d+\s*ov\b'                  # door count: 4ov
    r'|\d+\s*cm3'                     # engine size: 1898cm3
    r'|\d+[.,]\d'                     # displacement: 1.8, 2,0
    r'|/\d{2,4}'                      # approval/spec tail: /2400
    r'|-\d{3,}'                       # type code: -638094
    r'|-[A-Z]{2}\d{1,4}\b'            # variant code: -BA11
    r'|^(?:19|20)\d{2}\s+\S'          # year prefix: 2006 TOYOTA ...
    r'|^\d{5,}(?![0-9a-z])'           # long numeric code
    r'|\b(?:umpikorinen|viistoperä|avolavakuorma-auto|monikäyttöajoneuvo|yksikerroksinen|matalalattiainen)\b'
    r'|\b(?:4x4|4motion|4matic|automatic|automaatti|dsg\d*)\b'
)


def model_is_technical(model):
    """True when the value is a raw technical designation, not a model name."""
    return bool(TECHNICAL_MODEL_RE.search(clean(model)))


# The `[CO₂ …; veromassa …]` disambiguation suffix the builder used to append to keep rows
# with an identical visible label apart. It is no longer written; the constant strips the
# suffix off legacy input (`strip_variant_detail()`/`variant_base()`) and guards the build
# against it reappearing (`validate_catalog()`).
VARIANT_DETAIL_RE = re.compile(r'\s*\[[^\]]*\]\s*$')


def strip_variant_detail(variant):
    """Drop the legacy `[CO₂ …; veromassa …]` suffix off a variant label.

    The picker never showed that suffix, so the committed shards hold groups of rows that
    read identically once it is gone. `normalize_catalog()` strips it BEFORE building the
    merge key; otherwise those rows stay separate options and `validate_catalog()` rejects
    the leftover label. Only a trailing bracket is touched — a `, X kW` power suffix and a
    real parenthesised body suffix are part of the visible label and are kept.
    """
    return VARIANT_DETAIL_RE.sub('', str(variant or '')).strip()


def variant_base(variant):
    """Strip the ', X kW', ' (approval)' and ' [details]' suffixes off a variant."""
    value = strip_variant_detail(clean(variant))
    value = re.sub(r'\s*\([^()]*\)\s*$', '', value)
    value = re.sub(r',\s*\d+(?:[.,]\d+)?\s*kW\s*$', '', value, flags=re.I)
    return value.strip()


def visible_variant(variant, approval):
    """The variant text the picker shows: the type-approval suffix is stripped.

    `catalog_item()` appends ` ({approval})` to the variant while the picker hides that
    code (JS `cleanVariant()`), so two configurations that differ only by their type
    approval are indistinguishable for the user. They must be merged (or, when their cost
    drivers differ, labelled with the difference) instead of being listed twice.
    """
    value = str(variant or '')
    if approval:
        value = ''.join(value.split(f' ({approval})'))
    return re.sub(r'\s{2,}', ' ', value).strip()


# Technical noise that Traficom's `mallimerkinta` repeats inside a version label but the
# picker must not show: door counts (`4ov`, `5D`), body-style words and their letter codes
# (`Farmari`, `(AC)`, `Sedan`), transmission wording and type-approval code tails
# (`-1J/250`, `/266`, `-140028`). The engine itself — displacement, engine family
# (`TDI`/`CDI`), trims and the `, N kW` power suffix — is what identifies a version, so it
# is kept. The door patterns require a whitespace/start boundary so hyphenated engine codes
# (`D-4D`), Saab models (`9-3`) and trims (`4-MOTION`, `MX-5`) are never touched.
VARIANT_POWER_RE = re.compile(r'\s*,\s*\d+(?:[.,]\d+)?\s*kW\s*$', re.I)
VARIANT_BODY_CODE_RE = re.compile(r'\s*\([A-Z]{1,2}\)')
VARIANT_DOOR_RE = re.compile(
    r'(?:(?<=^)|(?<=\s))\d+\s*ov(?=\s|,|$)'          # 4ov
    r'|(?:(?<=^)|(?<=\s))[2-6][dD](?=\s|,|$|[A-Z])',  # 4D / 4DSEDAN (glued door code)
    re.I,
)
VARIANT_BODY_WORD_RE = re.compile(
    r'(?i)\b(?:sedan|hatchback|cabriolet|coupe|coupé|touring|st[wm]|farmari|viistoper[äa]|'
    r'avoauto|avolava|umpikorinen|monik[äa]ytt[öo]ajoneuvo|matkailuauto|combi|kombi|mpv|kasten|doppel)\b'
)
VARIANT_TRANSMISSION_RE = re.compile(r'(?i)\b(?:automatic|automat|autom)\b')
VARIANT_CODE_TAIL_RE = re.compile(r'(?i)-[a-z0-9]{1,6}/[0-9]{2,4}\b|/[0-9]{2,4}\b|-\d{3,}\b|-[a-z]{2}\d{1,4}\b')
VARIANT_CM3_RE = re.compile(r'(\d{3,4})\s*cm3', re.I)
VARIANT_LITRES_RE = re.compile(r'\b\d[.,]\d\b')
VARIANT_COMMA_DECIMAL_RE = re.compile(r'(\d),(\d)')


def _displacement_litres(cm3):
    """`5972cm3` -> `6`; `1995cm3` -> `2`; `1591cm3` -> `1.6`."""
    litres = int(cm3) / 1000
    return f'{litres:.1f}'.rstrip('0').rstrip('.')


def clean_variant(variant):
    """Reduce a Traficom model designation to the engine description the picker shows.

    The version list (`Moottori / käyttövoima`) must read like an engine, not a data
    sheet: `INSIGHT Viistoperä (AB) 4ov 1339cm3, 65 kW` becomes `INSIGHT 1.3, 65 kW`.
    Door counts, body words/codes, transmission wording and code tails are dropped;
    displacement is normalised to litres and the decimal comma to a point. When only
    noise was present, the result is empty (the picker then shows just the fuel and
    years), so a version is never left as a technical string.
    """
    value = clean(variant)
    if not value:
        return ''
    power_match = VARIANT_POWER_RE.search(value)
    power = power_match.group(0).strip() if power_match else ''
    if power_match:
        value = value[:power_match.start()].rstrip(' ,-/')
    value = VARIANT_BODY_CODE_RE.sub(' ', value)
    value = VARIANT_CODE_TAIL_RE.sub(' ', value)
    value = VARIANT_DOOR_RE.sub(' ', value)
    value = VARIANT_BODY_WORD_RE.sub(' ', value)
    value = VARIANT_TRANSMISSION_RE.sub(' ', value)
    if VARIANT_LITRES_RE.search(value):
        value = VARIANT_CM3_RE.sub(' ', value)
    else:
        value = VARIANT_CM3_RE.sub(lambda match: _displacement_litres(match.group(1)), value)
    value = re.sub(r'\s{2,}', ' ', value).strip(' ,-/')
    result = (value + (power if power else '')).strip(' ,-/')
    result = VARIANT_COMMA_DECIMAL_RE.sub(r'\1.\2', result)
    return re.sub(r'\s{2,}', ' ', result).strip(' ,-/')


def strip_model_from_variant(model, variant):
    """Drop a leading model-name prefix from a version label (case-insensitive).

    `catalog_item()` builds the variant from the model designation/commercial name, so
    it often starts with the model itself (`INSIGHT 1.3, 65 kW`). The Malli field already
    names the model, so that prefix is noise in the version list. Never applied to a row
    that `model_is_designation()` flags — those keep their variant so the designation
    detector still recognises them.
    """
    value = clean(variant)
    m = clean(model)
    if not value or not m:
        return value
    pattern = re.compile(r'(?i)^\s*' + re.escape(m) + r'\b')
    stripped = pattern.sub(' ', value, count=1)
    stripped = re.sub(r'\s{2,}', ' ', stripped).strip(' ,-/')
    return stripped or value


def strip_variant_code_letter(variant):
    """Drop a standalone Traficom variant-code letter (`2 A, 140 kW` -> `2, 140 kW`).

    The code letter always follows the displacement, so it is only stripped after a
    digit; a leading `A-2D` (Ford Model A + 2-door) is not a code letter and stays.
    """
    value = clean(variant)
    if not value:
        return ''
    value = re.sub(r'(?i)(?<=\d)\s+[Aa]\b', '', value)
    value = re.sub(r'\s+,\s*', ', ', value)  # collapse the gap left before a comma
    return re.sub(r'\s{2,}', ' ', value).strip(' ,-/')


def model_is_designation(model, variant):
    """True when Malli shows the raw technical designation (== variant base).

    Traficom's `kaupallinenNimi` is frequently empty; the builder then fell back
    to `mallimerkinta`, and the variant was built from that same value, so the
    variant's base ends up equal to the model (e.g. model `5D PASSAT VARIANT
    1.9TDI-3B/271` with variant `5D PASSAT VARIANT 1.9TDI-3B/271, 66 kW`). Such
    values are engine/body designations, not model names, so they must stay out of
    the Malli list while the engine remains visible in the next (variant) field.
    """
    base = variant_base(variant)
    model_key = canonical_model_key('', model)
    return bool(model_key) and model_key == canonical_model_key('', base)


def model_year_span(years):
    """(first, newest) first-registration years of a variant, or (None, None).

    `years` is written as `1998–2005`, `2005` or `Tuntematon`; an unusable value or a
    span outside 1886..SOURCE_DATE yields (None, None), matching `normalize_years()`.
    """
    match = re.fullmatch(r'(\d{4})(?:[–-](\d{4}))?', clean(years))
    if not match:
        return (None, None)
    start = int(match.group(1))
    end = int(match.group(2) or start)
    if start < 1886 or end < start or end > int(SOURCE_DATE[:4]):
        return (None, None)
    return (start, end)


def model_is_rare(registrations):
    """Fewer registered vehicles than `MIN_MODEL_REGISTRATIONS` (a one-off)."""
    return bool(MIN_MODEL_REGISTRATIONS) and registrations < MIN_MODEL_REGISTRATIONS


def model_is_obsolete(newest_year):
    """No usable registration year, or one older than `MIN_MODEL_YEAR`."""
    return newest_year is None or newest_year < MIN_MODEL_YEAR


def _brand_key_variants(brand):
    """Normalized make spellings that may be repeated in front of a model name."""
    norm = clean(brand)
    names = [norm]
    first = re.split(r'[\s\-,/]+', norm)[0] if norm else ''
    if first and first != norm:
        names.append(first)
    variants = {_model_norm(name) for name in names if len(_model_norm(name)) >= 4}
    variants |= set(EXTRA_MAKE_PREFIXES.get(_model_norm(norm), ()))
    return variants


def _one_edit_apart(first, second):
    """True when two normalized keys differ by one insertion, deletion or typo."""
    if first == second or abs(len(first) - len(second)) > 1:
        return False
    if len(first) == len(second):
        return sum(1 for a, b in zip(first, second) if a != b) == 1
    if len(first) > len(second):
        first, second = second, first
    index = 0
    skipped = False
    for char in second:
        if index < len(first) and first[index] == char:
            index += 1
        elif skipped:
            return False
        else:
            skipped = True
    return True


def strip_brand_typo_prefix(brand, value):
    """Drop a leading misspelled or run-together make token (`PORCHE 928` -> `928`).

    The catalogue was typed by hand, so the make is often repeated inside the model
    with a typo, glued together or with a different separator (`Porche Cayenne`,
    `Mercedez-Benz C 320`, `TOYTA YARIS`, `LANDROVER DEFENDER 130`,
    `Lynk & Co 01`). Only a token that is the make name (with `and`/`&` ignored)
    plus or minus one character is removed, and `Mazda2`/`OMODA5`/`POLESTAR2` (make
    plus digits) are never touched, so real model names are safe (`Fordson`,
    `Alfasud`, `EURAMOBIL`, `ADRIATIK`, `Hymermobil`).
    """
    tokens = clean(value).split()
    variants = _brand_key_variants(brand)
    if not tokens or not variants:
        return value
    for count in (3, 2, 1):
        if len(tokens) <= count:
            continue
        head = [token for token in tokens[:count] if _model_norm(token) != 'and']
        key = _model_norm(' '.join(head))
        remainder = ' '.join(tokens[count:]).strip(' -,')
        if not key or not remainder:
            continue
        for variant in variants:
            trailing = key[len(variant):] if key.startswith(variant) else ''
            if trailing and trailing.isdigit():
                continue
            if key == variant or _one_edit_apart(key, variant):
                return remainder
    return value


def strip_make_prefix(brand, value):
    """Drop an exact make prefix written with any separator (`Ford Transit` -> `Transit`)."""
    make_upper = clean(brand).upper()
    first = make_token(clean(brand)).upper()
    for prefix_make in dict.fromkeys([make_upper, first]):
        if not prefix_make:
            continue
        for sep in (' ', '-', '/', '–', '—', ',', '.'):
            if value.upper().startswith(prefix_make + sep):
                return value[len(prefix_make + sep):].strip()
        if value.upper() == prefix_make:
            return ''
    return value


# Abbreviations of a make that Traficom also writes INSIDE the model text (`VW PASSAT`,
# `MB C 220`, `M-B E200`) — applied only when the row's own make resolves to that make.
def strip_make_alias_prefix(brand, value):
    """Drop a make abbreviation repeated in the model name (`VW PASSAT` -> `PASSAT`)."""
    aliases = MODEL_MAKE_ALIAS_PREFIXES.get(normalize_brand_name(clean(brand)))
    if not aliases:
        return value
    upper = value.upper()
    for alias in sorted(aliases, key=len, reverse=True):
        token = alias.upper()
        for separator in (' ', '-', ',', '.', '/'):
            if upper.startswith(token + separator):
                remainder = value[len(alias) + 1:].strip(' -,/.')
                if re.search(r'[0-9A-Za-z]', remainder):
                    return remainder
    return value


def strip_make_from_model(brand, value):
    """Remove a repeated make from a model name without changing letter case."""
    original = clean(value)
    if not original:
        return ''
    brand_norm = clean(brand)
    value = strip_make_prefix(brand_norm, original)
    if value:
        value = strip_brand_typo_prefix(brand_norm, value)
    if value:
        value = strip_make_prefix(brand_norm, value)
    if value:
        value = strip_make_alias_prefix(brand_norm, value)
    return value or original


def normalize_model(brand, value):
    """Strip a leading make prefix and title-case pure-uppercase model names."""
    value = strip_make_from_model(brand, value)
    if value and value.isupper() and value.isalpha():
        return value.title()
    return value


# Real model names the automatic filters misclassify, so they must always stay in the
# Malli picker (inverse of `HIDDEN_MODELS`). `E-HS9` trips the variant-code pattern
# (`-HS9`), `4/44` trips the approval-tail pattern (`/44`), `TYPE 57C STELVIO` equals
# its own variant base (a designation false positive), and Irizar bus names carry
# length/height figures. Keys = `(clean(brand).casefold(), canonical_model_key(brand, model))`.
KEEP_MODELS = {
    (clean(brand).casefold(), canonical_model_key(brand, model))
    for brand, model in (
        ('Faw', 'E-HS9'),
        ('Wolseley', '4/44'),
        ('Bugatti', 'TYPE 57C STELVIO'),
        ('Irizar', 'i8 14.98 3.75'),
        ('Irizar', 'i6 15.37'),
        ('Irizar', '16 12.35 Efficient'),
        ('Irizar', '1613.35 Efficient'),
        # Modern EVs whose short commercial name equals its own variant base, so the
        # designation detector drops the whole make.
        ('Aion', 'Ut'),
        ('Aion', 'V'),
        ('Gac', 'AION V'),
        ('Rivian', 'R1T'),
        ('Zeekr', '001'),
        ('Skywell', 'ET5'),
        ('Skywell', 'BE11'),
    )
}


def model_is_kept(brand, model):
    """True when a curated entry must always be offered in the Malli picker."""
    return (clean(brand).casefold(), canonical_model_key(brand, model)) in KEEP_MODELS


def normalize_years(value):
    start, end = model_year_span(value)
    if start is None:
        return 'Tuntematon'
    return str(start) if start == end else f'{start}–{end}'


def source_record(item):
    return {
        'id': item.get('id', ''),
        'type_approval': item.get('type_approval', ''),
        'variant_code': item.get('variant_code', ''),
        'version_code': item.get('version_code', ''),
        'eea_type_approval': item.get('eea_type_approval', ''),
        'vehicle_class': item.get('vehicle_class', ''),
        'body_type': item.get('body_type', ''),
        'road_mass': item.get('road_mass', 0),
        'technical_mass': item.get('technical_mass', 0),
        'curb_mass': item.get('curb_mass', 0),
        'tax_mass': item.get('tax_mass', 0),
    }


CALCULATION_FIELDS = (
    'fuel_consumption', 'electric_consumption', 'co2', 'mass', 'tax_measurement',
    'tax_power_source', 'service_cost', 'service_interval_km', 'service_interval_months',
    'consumption_source', 'service_source', 'vehicle_class', 'body_type', 'seats',
    'tax_mass', 'mass_source',
)


def build_brand_resolver(items):
    """Map any raw brand spelling to the single selectable make.

    `items` must already carry alias/suffix-normalized brand names. Unlike the
    first-token collapse, composites such as "Mercedes-Benz-Dethleffs" collapse
    into the longest trusted base make that stands on its own in the catalogue.
    """
    raw_freq = Counter()
    display_of = {}
    for item in items:
        key = item['brand'].casefold()
        raw_freq[key] += int(item.get('registered_count', 0))
        current = display_of.get(key)
        if current is None or len(item['brand']) < len(current):
            display_of[key] = item['brand']

    collapsed_to = {}
    for key in raw_freq:
        if not any(sep in key for sep in (',', ' ', '-', '/', '–')):
            continue
        first = make_token(key)
        if first and first != key and first in raw_freq and raw_freq[first] >= 100:
            collapsed_to[key] = first

    stage_one = defaultdict(Counter)
    for item in items:
        resolved = collapsed_to.get(item['brand'].casefold(), item['brand'].casefold())
        display = display_of.get(resolved, item['brand'])
        stage_one[canonical_brand_key(display)][display] += int(item.get('registered_count', 0))

    brand_totals = {key: sum(names.values()) for key, names in stage_one.items()}
    trusted_keys = {key for key, total in brand_totals.items() if total >= 100}
    prefix_to = {}
    for key in stage_one:
        base = None
        for candidate in trusted_keys:
            if candidate == key or not key.startswith(candidate + ' '):
                continue
            if base is None or len(candidate) > len(base):
                base = candidate
        if base:
            prefix_to[key] = base

    brand_weights = defaultdict(Counter)
    for key, names in stage_one.items():
        brand_weights[prefix_to.get(key, key)].update(names)

    # Final pass: makes that differ only by spaces/dots/hyphens ("De Lorean" vs
    # "DeLorean", "T.E.C." vs "Tec") are the same selectable make.
    def fold_key(key):
        return re.sub(r'[^0-9a-z]+', '', key)

    folded = defaultdict(Counter)
    for key, names in brand_weights.items():
        folded[fold_key(key)].update(names)
    canonical_brands = {
        folded_key: sorted(names, key=lambda name: (-names[name], name.casefold(), len(name), name))[0]
        for folded_key, names in folded.items()
    }

    def resolve_brand(brand):
        resolved = collapsed_to.get(brand.casefold(), brand.casefold())
        display = display_of.get(resolved, brand)
        key = prefix_to.get(canonical_brand_key(display), canonical_brand_key(display))
        return canonical_brands.get(fold_key(key), normalize_brand_name(display))

    return resolve_brand


def normalize_catalog(items):
    # Expand make abbreviations (MB/VW) and strip legal-form suffixes up front so
    # that "Bürstner", "Bürstner GmbH" and "Mb-Dethleffs", "M-B Dethleffs",
    # "Mercedes-Benz-Dethleffs" all resolve to the same selectable make.
    items = [dict(item, brand=normalize_brand_name(item['brand'])) for item in items]
    resolve_brand = build_brand_resolver(items)

    # One display spelling per model within a make: a repeated make, case, spaces
    # and separators are treated as the same model so "CORAL S 670 SL" and
    # "Coral S_670SL" stop appearing as separate "Malli" entries. Prefer mixed case
    # over ALL CAPS.
    model_weights = defaultdict(Counter)
    for item in items:
        brand = resolve_brand(item['brand'])
        model = model_typo_fix(brand, clean(item['model']))
        model = strip_body_words(strip_engine_words(strip_make_from_model(brand, model)))
        key = (canonical_brand_key(brand), model_series_key(brand, model))
        model_weights[key][model] += int(item.get('registered_count', 0))
    canonical_models = {key: model_display(names) for key, names in model_weights.items()}

    merged = {}
    for original in items:
        item = dict(original)
        item['brand'] = resolve_brand(item['brand'])
        fixed_model = model_typo_fix(item['brand'], clean(item['model']))
        model_key = (canonical_brand_key(item['brand']), model_series_key(item['brand'], fixed_model))
        item['model'] = canonical_models.get(model_key, fixed_model)
        item['years'] = normalize_years(item.get('years', ''))
        item['vehicle_type'] = vehicle_type(item.get('vehicle_class', 'M1'), item.get('body_type', ''), item.get('seats', 0), item.get('vehicle_group', ''))
        # One row per label the picker shows (brand/model/fuel/variant/years, plus the vehicle
        # type when no type filter is chosen): two rows that read the same are the same car for
        # the user, so they merge even when a cost-driving value differs. The picker shows
        # neither the type-approval code (`visible_variant()`) nor the legacy `[CO₂ …]` suffix
        # the builder once appended, so both are stripped before the merge key is built.
        item['variant'] = clean_variant(
            visible_variant(strip_variant_detail(item.get('variant')), item.get('type_approval'))
        )
        if not model_is_designation(item['model'], item['variant']):
            item['variant'] = strip_variant_code_letter(
                clean_variant(strip_model_from_variant(item['model'], item['variant']))
            )
        key = (item['brand'], item['model'], item['powertrain'], item['variant'], item['years'], item['vehicle_type'], visible_body(item.get('body_type', '')))
        if key not in merged:
            merged[key] = item
            continue
        # The most registered raw variant (`source_rank` 1) supplies the recorded values.
        current = merged[key]
        base_item, other = (
            (item, current)
            if int(item.get('source_rank', 0)) < int(current.get('source_rank', 0))
            else (current, item)
        )
        base_item['registered_count'] = int(base_item.get('registered_count', 0)) + int(other.get('registered_count', 0))
        provenance = base_item.get('source_records') or [source_record(base_item)]
        provenance.extend(other.get('source_records') or [source_record(other)])
        base_item['source_records'] = list({record['id']: record for record in provenance if record.get('id')}.values())
        merged[key] = base_item

    normalized = list(merged.values())

    # Safety net: guarantee uniqueness even for input that bypassed the merge key above.
    label = lambda entry: (
        entry['brand'], entry['model'], entry['powertrain'], entry['variant'],
        entry.get('years', ''), entry['vehicle_type'], visible_body(entry.get('body_type', '')),
    )
    used_labels = set()
    for item in normalized:
        current_label = label(item)
        collision = 1
        while current_label in used_labels:
            collision += 1
            item['variant'] = f"{item['variant'].split(' #')[0]} #{collision}"
            current_label = label(item)
        used_labels.add(current_label)

    normalized.sort(
        key=lambda item: (
            int(item.get('source_rank', 0)), item['brand'].casefold(), item['model'].casefold(),
            item['powertrain'], item['variant'].casefold(), item.get('years', ''),
        )
    )
    return normalized


def first_year(value):
    match = re.search(r'(\d{4})', clean(value))
    return int(match.group(1)) if match else None


def powertrain(row):
    source = clean(row.get('kayttovoima'))
    hybrid = clean(row.get('sahkohybridi')).lower() == 'true'
    hybrid_class = clean(row.get('sahkohybridinluokka'))
    if source == '04':
        return 'electric'
    if hybrid and hybrid_class == '01':
        return 'phev'
    if hybrid:
        return 'hybrid'
    if source == '02':
        return 'diesel'
    if source == '01':
        return 'petrol'
    return None


def numeric(value):
    try:
        return float(str(value).replace(',', '.'))
    except (TypeError, ValueError):
        return 0.0


def technical_co2(row):
    for field, measurement in (('WLTP2_Co2', 'wltp'), ('WLTP_Co2', 'wltp'), ('NEDC2_Co2', 'nedc'), ('NEDC_Co2', 'nedc')):
        value = numeric(row.get(field))
        if value > 0:
            return round(value), measurement
    return 0, 'wltp'


def tax_power_source(row):
    return {'01': 'petrol', '02': 'diesel', '04': 'electricity'}.get(clean(row.get('kayttovoima')), 'petrol')


def estimate_consumption(kind, co2):
    """Cost defaults only. They are explicitly not Traficom consumption values."""
    if kind == 'diesel':
        return round(co2 / 26.4, 1) if co2 else 6.2
    if kind in ('petrol', 'hybrid'):
        return round(co2 / 23.92, 1) if co2 else (6.8 if kind == 'petrol' else 5.0)
    if kind == 'phev':
        return round(max(2.2, co2 / 23.92), 1)
    return 0


def estimate_electricity(kind, mass):
    if kind == 'electric':
        return round(max(15.0, min(26.0, 11.0 + mass / 180)), 1)
    if kind == 'phev':
        return round(max(16.0, min(24.0, 10.5 + mass / 200)), 1)
    return 0


def write_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    temp_path.write_text(content, encoding='utf-8')
    os.replace(temp_path, path)


def write_php(path, value):
    encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    content = "<?php\n/** Generated from Traficom open data. Do not edit manually. */\n" \
        "defined( 'ABSPATH' ) || exit;\n\n" \
        "return json_decode( '" + encoded.replace('\\', '\\\\').replace("'", "\\'") + "', true );\n"
    write_atomic(path, content)


def model_shard(brand, model):
    identity = (brand + '\0' + model).encode('utf-8')
    return hashlib.sha256(identity).hexdigest()[:2]


SUPPORTED_VEHICLE_TYPES = {'passenger', 'light_truck', 'minibus', 'van', 'motorhome', 'bus', 'special', 'pickup'}


def model_statistics(items):
    """Per (brand, model) registered vehicles and newest first-registration year."""
    registrations = Counter()
    newest = {}
    for item in items:
        key = (item['brand'], item['model'])
        registrations[key] += int(item.get('registered_count', 0) or 0)
        _, end = model_year_span(item.get('years', ''))
        if end is not None and end > newest.get(key, 0):
            newest[key] = end
    return registrations, newest


def model_hide_reason(brand, model, brand_total, model_total, newest_year):
    """Why the Malli picker keeps a (brand, model) pair out, or '' when it is offered.

    The order matches the checks in `selectable_models()`, so the report tools explain
    every hidden pair with the same vocabulary.
    """
    if MIN_BRAND_REGISTRATIONS and brand_total < MIN_BRAND_REGISTRATIONS:
        return 'rare-brand'
    if brand_is_hidden(brand):
        return 'curated-hidden-brand'
    if brand_is_placeholder(brand):
        return 'placeholder-brand'
    if model_is_hidden(brand, model):
        return 'curated-hidden'
    if model_is_kept(brand, model):
        return ''
    if model_is_unknown(brand, model):
        return 'unknown'
    if model_is_technical(model):
        return 'technical'
    if model_is_rare(model_total) and model_is_obsolete(newest_year):
        return 'rare+old'
    return ''


def selectable_models(items):
    """The (brand, model, vehicle_type) rows offered in the Malli picker.

    Drops placeholder/curated/one-off makes, raw technical designations that repeat the
    variant, curated model entries and models that are BOTH rare
    (`MIN_MODEL_REGISTRATIONS`) and old (`MIN_MODEL_YEAR`). Returns a mapping from each
    (brand, model, vehicle_type) row to the sorted powertrain codes it has, so every step
    of the picker cascade can hide what does not match the previous choice. Shard data is
    kept, so the registered-vehicle total is unchanged.
    """
    brand_registrations = Counter()
    for item in items:
        brand_registrations[item['brand']] += int(item.get('registered_count', 0) or 0)
    # Rare/one-off makes are hidden from the picker; their shard data is kept so the
    # registered-vehicle total stays intact.
    rare_brands = {
        brand for brand, total in brand_registrations.items()
        if MIN_BRAND_REGISTRATIONS and total < MIN_BRAND_REGISTRATIONS
    }
    model_registrations, model_newest = model_statistics(items)
    blocked = {}

    def model_is_blocked(brand, model):
        key = (brand, model)
        cached = blocked.get(key)
        if cached is None:
            cached = bool(model_hide_reason(
                brand, model, brand_registrations[brand], model_registrations[key], model_newest.get(key),
            ))
            blocked[key] = cached
        return cached

    models = {}
    for item in items:
        brand = item['brand']
        if brand in rare_brands or brand_is_hidden(brand) or brand_is_placeholder(brand):
            continue
        if model_is_blocked(brand, item['model']):
            continue
        if not model_is_kept(brand, item['model']) and model_is_designation(item['model'], item.get('variant', '')):
            continue
        key = (brand, item['model'], item['vehicle_type'])
        codes = models.setdefault(key, set())
        code = item.get('powertrain') or ''
        if code:
            codes.add(code)
    return {key: tuple(sorted(codes)) for key, codes in models.items()}


def powertrain_availability(models):
    """{make: {vehicle_type: [powertrain codes]}} for the picker facet endpoint."""
    availability = defaultdict(lambda: defaultdict(set))
    for (brand, _, kind), codes in models.items():
        availability[brand][kind].update(codes)
    return {
        brand: {kind: sorted(codes) for kind, codes in sorted(kinds.items())}
        for brand, kinds in sorted(availability.items())
    }


def validate_index(index, items, models=None):
    """Fail the build when the generated picker index breaks its invariants."""
    if index['count'] != len(items):
        raise ValueError('Picker index count does not match the catalogue size.')
    expected = selectable_models(items) if models is None else models
    listed = Counter(
        (entry['brand'], entry['model'], entry['vehicle_type']) for entry in index['models']
    )
    duplicates = [entry for entry, count in listed.items() if count > 1]
    if duplicates:
        raise ValueError(f'Picker index lists a model row twice: {duplicates[0]!r}')
    if set(listed) != set(expected):
        missing = sorted(set(expected) - set(listed))[:3]
        unexpected = sorted(set(listed) - set(expected))[:3]
        raise ValueError(
            'Picker index does not match the selectable models '
            f'(missing={missing!r}, unexpected={unexpected!r}).'
        )
    for entry in index['models']:
        key = (entry['brand'], entry['model'], entry['vehicle_type'])
        codes = tuple(entry.get('powertrains') or ())
        if codes != expected[key]:
            raise ValueError(f'Picker index powertrains do not match the catalogue for {key!r}.')
        if not codes:
            raise ValueError(f'Picker index model row has no powertrain: {key!r}.')
        if any(code not in POWERTRAIN_CODES for code in codes):
            raise ValueError(f'Picker index has an unsupported powertrain code: {key!r} {codes!r}.')
        if MODEL_ENGINE_WORDS_RE.search(entry['model']):
            raise ValueError(f'Picker index model name still carries engine wording: {key!r}.')
        if strip_body_words(entry['model']) != entry['model']:
            raise ValueError(f'Picker index model name still carries body wording: {key!r}.')
    if index.get('availability') != powertrain_availability(expected):
        raise ValueError('Picker index availability map does not match the catalogue.')
    brands = {brand for brand, _, _ in expected}
    if not brands:
        raise ValueError('Picker index has no selectable makes.')
    if index['brands'] != sorted(brands, key=str.casefold):
        raise ValueError('Picker index brand list does not match the selectable models.')
    if any(kind not in SUPPORTED_VEHICLE_TYPES for kind in index['vehicleTypes']):
        raise ValueError('Picker index contains an unsupported vehicle type.')


def validate_catalog(items):
    """Guards that must hold before the selectable index is written.

    `variant` carries neither the type-approval code (see `visible_variant()`) nor a
    `[CO₂ …]` disambiguation suffix any more, so the selector-label check below is exactly
    the version list the picker builds (`fuel · variant · body · years`): a duplicate here is
    a duplicate the user would see, and a bracketed label is the noise we dropped.
    """
    if len({item['id'] for item in items}) != len(items):
        raise ValueError('Catalogue normalization produced duplicate IDs.')
    bracketed = next((item['variant'] for item in items if VARIANT_DETAIL_RE.search(item['variant'])), None)
    if bracketed:
        raise ValueError(f'Catalogue normalization produced a bracketed variant label: {bracketed!r}')
    noisy = next(
        (
            item['variant'] for item in items
            if VARIANT_DOOR_RE.search(item['variant'])
            or VARIANT_CM3_RE.search(item['variant'])
            or VARIANT_BODY_CODE_RE.search(item['variant'])
        ),
        None,
    )
    if noisy:
        raise ValueError(f'Catalogue normalization produced a technical-noise variant label: {noisy!r}')
    visible_labels = [
        (item['brand'], item['model'], item['powertrain'], item['variant'], item['years'], item['vehicle_type'], visible_body(item.get('body_type', '')))
        for item in items
    ]
    if len(set(visible_labels)) != len(visible_labels):
        counts = Counter(visible_labels)
        sample = next(label for label, number in counts.items() if number > 1)
        raise ValueError(f'Catalogue normalization produced duplicate selector labels: {sample!r}')
    if any(item.get('vehicle_type') not in SUPPORTED_VEHICLE_TYPES for item in items):
        raise ValueError('Catalogue normalization produced an unsupported vehicle type.')


def write_catalog(items, normalize=True):
    registration_total = sum(int(item.get('registered_count', 0)) for item in items)
    if normalize:
        items = normalize_catalog(items)
        if registration_total != sum(int(item.get('registered_count', 0)) for item in items):
            raise ValueError('Catalogue normalization changed the registered-vehicle total.')
        validate_catalog(items)
    shards = defaultdict(list)
    vehicle_types = set()
    for item in items:
        vehicle_types.add(item['vehicle_type'])
        shards[model_shard(item['brand'], item['model'])].append(item)
    # A make is only offered when it still has at least one selectable model.
    models = selectable_models(items)
    brands = {brand for brand, _, _ in models}

    index = {
        'count': len(items),
        'brands': sorted(brands, key=str.casefold),
        'vehicleTypes': sorted(vehicle_types),
        'models': [
            {
                'brand': brand,
                'model': model,
                'vehicle_type': kind,
                'powertrains': list(models[(brand, model, kind)]),
            }
            for brand, model, kind in sorted(models, key=lambda item: (item[0].casefold(), item[1].casefold(), item[2]))
        ],
        'availability': powertrain_availability(models),
    }
    validate_index(index, items, models)
    shard_directories = (OUT_SHARDS, DIST_DATA / OUT_SHARDS.name)
    for directory in shard_directories:
        if directory.exists():
            for previous in directory.glob('*.json.gz'):
                previous.unlink()
        else:
            directory.mkdir(parents=True, exist_ok=True)
        for shard, entries in shards.items():
            shard_path = directory / f'{shard}.json.gz'
            temp_path = shard_path.with_name(f'.{shard_path.name}.{os.getpid()}.tmp')
            with gzip.open(temp_path, 'wt', encoding='utf-8', newline='') as output:
                json.dump(entries, output, ensure_ascii=False, separators=(',', ':'))
            os.replace(temp_path, shard_path)

    write_php(OUT_FILE, index)
    write_php(DIST_DATA / OUT_FILE.name, index)


def catalog_id(entry):
    identity = json.dumps(entry, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    return 'traficom-' + hashlib.sha256(identity).hexdigest()[:20]


def catalog_item(rank, stock_count, start, end, entry):
    _, vehicle_class, body_type, seats, brand, model, model_designation, commercial_name, approval, variant_code, version_code, kind, co2, tax_measurement, tax_power, road_mass, technical_mass, curb_mass, power, vehicle_group = entry
    years = 'Tuntematon' if not start or not end else str(start) if start == end else f'{start}–{end}'
    variant_name = normalize_model(brand, model_designation or commercial_name or model)
    if power:
        variant_name += f', {power:g} kW'
    if approval:
        variant_name += f' ({approval})'
    return {
        'id': catalog_id(entry),
        'brand': brand.title() if brand.isupper() else brand,
        'model': model,
        'variant': variant_name,
        'vehicle_type': vehicle_type(vehicle_class, body_type, seats, vehicle_group),
        'vehicle_group': vehicle_group,
        'vehicle_class': vehicle_class,
        'body_type': body_type,
        'seats': seats,
        'years': years,
        'powertrain': kind,
        'fuel_consumption': estimate_consumption(kind, co2),
        'electric_consumption': estimate_electricity(kind, road_mass or technical_mass or curb_mass),
        'co2': co2,
        'mass': road_mass or technical_mass or curb_mass,
        'tax_mass': road_mass,
        'mass_source': 'road_traffic' if road_mass else 'technical_fallback' if technical_mass else 'curb_mass_fallback' if curb_mass else 'unknown',
        'road_mass': road_mass,
        'technical_mass': technical_mass,
        'curb_mass': curb_mass,
        'tax_measurement': tax_measurement,
        'tax_power_source': tax_power,
        'service_cost': 360,
        'service_interval_km': 15000,
        'service_interval_months': 12,
        'consumption_source': 'CO2-derived/default estimate; no matching official EEA record',
        'service_source': 'Public benchmark: Traficom calculator methodology (annualised); VIN/manufacturer plan required',
        'source': 'Traficom open vehicle data, 30.6.2026 (CC BY 4.0)',
        'source_rank': rank,
        'registered_count': stock_count,
        'type_approval': approval,
        'variant_code': variant_code,
        'version_code': version_code,
        'data_status': 'technical-fields-verified; cost-drivers-estimated',
    }


def main():
    if not VEHICLES_FILE.exists():
        sys.exit('Official Traficom source files are missing from /tmp.')
    with acquire_catalog_lock():
        variants = {}
        excluded = Counter()
        included_registrations = Counter()
        included_missing_road_mass = Counter()
        supported_classes = {'M1', 'M1G', 'N1', 'N1G', 'M2', 'M2G', 'M3', 'M3G'}

        with zipfile.ZipFile(VEHICLES_FILE) as archive:
            csv_name = archive.namelist()[0]
            with archive.open(csv_name) as raw:
                reader = csv.DictReader(TextIOWrapper(raw, encoding='iso-8859-1'), delimiter=';')
                for row in reader:
                    vehicle_class = clean(row.get('ajoneuvoluokka')).upper()
                    if vehicle_class not in supported_classes:
                        continue
                    brand = clean(row.get('merkkiSelvakielinen'))
                    model = normalize_model(brand, clean(row.get('kaupallinenNimi')) or clean(row.get('mallimerkinta')))
                    key = model_key(brand, model)
                    if not all(key):
                        excluded[f'{vehicle_class}:missing_make_model'] += 1
                        continue
                    kind = powertrain(row)
                    if not kind:
                        excluded[f'{vehicle_class}:unsupported_fuel_{clean(row.get("kayttovoima")) or "blank"}'] += 1
                        continue
                    road_mass = round(numeric(row.get('tieliikSuurSallKokmassa')))
                    technical_mass = round(numeric(row.get('teknSuurSallKokmassa')))
                    curb_mass = round(numeric(row.get('omamassa')))
                    co2, tax_measurement = technical_co2(row)
                    body_type = clean(row.get('korityyppi')).upper()
                    vehicle_group = clean(row.get('ajoneuvoryhma'))
                    seats = round(numeric(row.get('istumapaikkojenLkm')))
                    entry = (
                        key,
                        vehicle_class,
                        body_type,
                        seats,
                        brand,
                        model,
                        clean(row.get('mallimerkinta')),
                        clean(row.get('kaupallinenNimi')),
                        clean(row.get('tyyppihyvaksyntanro')),
                        clean(row.get('variantti')),
                        clean(row.get('versio')),
                        kind,
                        co2,
                        tax_measurement,
                        tax_power_source(row),
                        road_mass,
                        technical_mass,
                        curb_mass,
                        round(numeric(row.get('suurinNettoteho')), 1),
                        vehicle_group,
                    )
                    registration_year = first_year(row.get('ensirekisterointipvm'))
                    aggregate = variants.get(entry)
                    if aggregate is None:
                        variants[entry] = [1, registration_year, registration_year]
                    else:
                        aggregate[0] += 1
                        if registration_year:
                            aggregate[1] = registration_year if aggregate[1] is None else min(aggregate[1], registration_year)
                            aggregate[2] = registration_year if aggregate[2] is None else max(aggregate[2], registration_year)
                    included_registrations[vehicle_class] += 1
                    if road_mass <= 0:
                        included_missing_road_mass[vehicle_class] += 1

        ordered_variants = sorted(variants.items(), key=lambda item: (-item[1][0], item[0]))
        items = [
            catalog_item(rank, aggregate[0], aggregate[1], aggregate[2], entry)
            for rank, (entry, aggregate) in enumerate(ordered_variants, start=1)
        ]
        write_catalog(items)
        powertrains = Counter(item['powertrain'] for item in items)
        models = {(item['brand'], item['model']) for item in items}
        compressed_size = sum(path.stat().st_size for path in OUT_SHARDS.glob('*.json.gz'))
        print(f'Wrote {len(items)} unique technical configurations across {len(models)} models')
        print(f'Powertrains: {dict(sorted(powertrains.items()))}')
        print(f'Registrations by vehicle class: {dict(sorted(included_registrations.items()))}')
        print(f'Registrations using fallback mass: {dict(sorted(included_missing_road_mass.items()))}')
        print(f'Excluded records by reason: {dict(sorted(excluded.items()))}')
        print(f'Compressed shards: {len(list(OUT_SHARDS.glob("*.json.gz")))} files, {compressed_size:,} bytes')
        print(f'Index: {OUT_FILE.stat().st_size:,} bytes')
        print('Most registered variants:', [(item['brand'], item['model'], item['registered_count']) for item in items[:5]])


if __name__ == '__main__':
    main()
