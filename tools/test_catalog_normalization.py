import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from build_traficom_catalog import (
    MIN_MODEL_REGISTRATIONS,
    MIN_MODEL_YEAR,
    acquire_catalog_lock,
    brand_is_placeholder,
    canonical_brand_key,
    canonical_model_key,
    clean_variant,
    model_is_designation,
    model_is_obsolete,
    model_is_rare,
    model_is_technical,
    model_is_unknown,
    model_series_key,
    model_typo_fix,
    model_year_span,
    normalize_brand_name,
    normalize_catalog,
    normalize_model,
    normalize_years,
    powertrain_availability,
    selectable_models,
    strip_body_words,
    strip_engine_words,    visible_body,    strip_variant_detail,
    validate_catalog,
    validate_index,
    vehicle_type,
    main,
)


def catalog_item(identifier, **overrides):
    item = {
        'id': identifier,
        'brand': 'Fiat-Pössl',
        'model': 'Ducato Camper',
        'variant': 'Camper Matkailuauto (AF)',
        'years': '2022',
        'powertrain': 'diesel',
        'vehicle_type': 'passenger',
        'fuel_consumption': 9.5,
        'electric_consumption': 0,
        'co2': 250,
        'mass': 3500,
        'tax_measurement': 'wltp',
        'tax_power_source': 'diesel',
        'service_cost': 360,
        'service_interval_km': 15000,
        'service_interval_months': 12,
        'consumption_source': 'estimate',
        'service_source': 'estimate',
        'registered_count': 1,
        'source_rank': 1,
        'type_approval': f'approval-{identifier}',
        'variant_code': f'variant-{identifier}',
        'version_code': f'version-{identifier}',
    }
    item.update(overrides)
    return item


class CatalogNormalizationTests(unittest.TestCase):
    def test_brand_separators_are_normalized_without_joining_words(self):
        self.assertEqual(canonical_brand_key('Fiat-Pössl'), canonical_brand_key('FIAT/Pössl'))
        self.assertNotEqual(canonical_brand_key('A-B'), canonical_brand_key('AB'))

    def test_vehicle_type_uses_official_class_and_body_codes(self):
        self.assertEqual(vehicle_type('M1', 'SA'), 'motorhome')
        self.assertEqual(vehicle_type('M1', 'AF'), 'passenger')
        self.assertEqual(vehicle_type('N1', 'BB'), 'van')
        self.assertEqual(vehicle_type('N1', 'BA'), 'light_truck')
        self.assertEqual(vehicle_type('M2', 'CA', 17), 'minibus')
        self.assertEqual(vehicle_type('M3', 'CA', 51), 'bus')

    def test_vehicle_type_uses_official_group_codes(self):
        self.assertEqual(vehicle_type('M1', '', 4, '29'), 'motorhome')
        self.assertEqual(vehicle_type('M1', '', 9, '35'), 'minibus')
        self.assertEqual(vehicle_type('M1G', '', 4), 'passenger')
        self.assertEqual(vehicle_type('M1G', 'SA', 4), 'motorhome')
        self.assertEqual(vehicle_type('M1', '', 51, '42'), 'bus')
        self.assertEqual(vehicle_type('M1', 'SC', 2), 'special')
        self.assertEqual(vehicle_type('N1G', 'BB', 3), 'van')
        self.assertEqual(vehicle_type('M1', '', 4, '21, 29'), 'motorhome')

    def test_invalid_registration_year_is_unknown(self):
        self.assertEqual(normalize_years('9999–0'), 'Tuntematon')
        self.assertEqual(normalize_years('2020–2024'), '2020–2024')

    def test_merge_keeps_all_source_identifiers(self):
        first = catalog_item('source-a', registered_count=2, source_rank=4)
        second = catalog_item('source-b', brand='Fiat/Pössl', registered_count=3, source_rank=2)

        result = normalize_catalog([first, second])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['registered_count'], 5)
        self.assertEqual(result[0]['id'], 'source-b')
        self.assertEqual(
            {record['id'] for record in result[0]['source_records']},
            {'source-a', 'source-b'},
        )
        self.assertEqual(len(result[0]['source_records']), 2)
        repeated = normalize_catalog(result)
        self.assertEqual(repeated[0]['source_records'], result[0]['source_records'])

    def test_distinct_cost_inputs_merge_into_one_visible_option(self):
        first = catalog_item('source-a', registered_count=2)
        second = catalog_item('source-b', co2=260)

        result = normalize_catalog([first, second])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['variant'], 'Camper')
        self.assertNotIn('[', result[0]['variant'])
        self.assertEqual(result[0]['registered_count'], 3)

    def test_main_uses_the_normalized_catalog_writer(self):
        with tempfile.TemporaryDirectory() as tempdir:
            zip_path = Path(tempdir) / 'vehicles.zip'
            with zipfile.ZipFile(zip_path, 'w') as archive:
                archive.writestr(
                    'data.csv',
                    '\n'.join([
                        'ajoneuvoluokka;merkkiSelvakielinen;kaupallinenNimi;mallimerkinta;kayttovoima;tieliikSuurSallKokmassa;teknSuurSallKokmassa;omamassa;tyyppihyvaksyntanro;variantti;versio;korityyppi;ajoneuvoryhma;istumapaikkojenLkm;ensirekisterointipvm;suurinNettoteho',
                        'M1;Volvo;XC60;XC60;Diesel;2500;2500;2000;ABC;XC60 Farmari (AC) 4ov 2400cm3 A, 140 kW [CO₂ 168 g/km];XYZ;AF;;5;2024;140',
                    ])
                )
            with patch('build_traficom_catalog.VEHICLES_FILE', zip_path), patch('build_traficom_catalog.write_catalog') as mock_write:
                main()

        self.assertEqual(mock_write.call_count, 1)
        self.assertEqual(mock_write.call_args.kwargs, {})
        self.assertTrue(mock_write.call_args.args)

    def test_catalog_generation_lock_prevents_parallel_runs(self):
        with tempfile.TemporaryDirectory() as tempdir:
            lock_path = Path(tempdir) / 'catalog.lock'
            with acquire_catalog_lock(lock_path):
                with self.assertRaises(RuntimeError):
                    with acquire_catalog_lock(lock_path):
                        pass

    def test_most_registered_source_supplies_the_values(self):
        first = catalog_item('source-a', registered_count=2, source_rank=2)
        second = catalog_item('source-b', co2=260, registered_count=3, source_rank=1)

        forward = normalize_catalog([first, second])
        backward = normalize_catalog([second, first])

        for result in (forward, backward):
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['id'], 'source-b')
            self.assertEqual(result[0]['co2'], 260)
            self.assertEqual(result[0]['registered_count'], 5)

    def test_brand_aliases_and_legal_suffixes_are_normalized(self):
        self.assertEqual(normalize_brand_name('Mb-Dethleffs'), 'Mercedes-Benz-Dethleffs')
        self.assertEqual(normalize_brand_name('M-B Dethleffs'), 'Mercedes-Benz Dethleffs')
        self.assertEqual(normalize_brand_name('Mercedes Benz-Dethleffs'), 'Mercedes-Benz-Dethleffs')
        self.assertEqual(normalize_brand_name('Bürstner GmbH'), 'Bürstner')
        self.assertEqual(normalize_brand_name('Equi-Trek Limited'), 'Equi-Trek')
        self.assertEqual(normalize_brand_name('Vw'), 'Volkswagen')

    def test_converter_brand_collapses_to_base_make(self):
        base = catalog_item('base', brand='Mercedes-Benz', model='Sprinter', registered_count=500)
        combo = catalog_item('combo', brand='Mb-Dethleffs', model='Camper', registered_count=5)

        result = normalize_catalog([base, combo])

        self.assertEqual({item['brand'] for item in result}, {'Mercedes-Benz'})
        self.assertEqual(sum(item['registered_count'] for item in result), 505)

    def test_model_case_and_separator_variants_collapse(self):
        first = catalog_item('first', brand='Adria', model='CORAL S 670 SL', variant='X')
        second = catalog_item('second', brand='Adria', model='Coral S 670 SL', variant='X')

        result = normalize_catalog([first, second])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['model'], 'Coral S 670 SL')
        self.assertEqual(result[0]['registered_count'], 2)

    def test_known_brand_typos_are_corrected(self):
        self.assertEqual(normalize_brand_name('BWW'), 'BMW')
        self.assertEqual(normalize_brand_name('Bww'), 'BMW')
        self.assertEqual(normalize_brand_name('Volswagen'), 'Volkswagen')
        self.assertEqual(normalize_brand_name('Hundai'), 'Hyundai')
        self.assertEqual(normalize_brand_name('Pösll'), 'Pössl')
        self.assertEqual(normalize_brand_name('Poessl'), 'Pössl')
        self.assertEqual(normalize_brand_name('Burstner'), 'Bürstner')
        self.assertEqual(normalize_brand_name('Garthago'), 'Carthago')
        self.assertEqual(normalize_brand_name('Studebacker'), 'Studebaker')
        self.assertEqual(normalize_brand_name('Saxas Nutzfahr Wrdau'), 'Saxas Nutzfahrzeuge Werdau')

    def test_lookalike_marques_are_not_merged(self):
        self.assertNotEqual(normalize_brand_name('Mazda'), normalize_brand_name('Matra'))
        self.assertNotEqual(normalize_brand_name('Fiat'), normalize_brand_name('Faw'))
        self.assertNotEqual(normalize_brand_name('Man'), normalize_brand_name('Mini'))

    def test_placeholder_makes_are_flagged(self):
        self.assertTrue(brand_is_placeholder('Ks. Huom.'))
        self.assertTrue(brand_is_placeholder('Övriga'))
        self.assertTrue(brand_is_placeholder('Omavalmiste'))
        self.assertFalse(brand_is_placeholder('Volvo'))

    def test_bmw_typo_merges_into_one_make(self):
        good = catalog_item('a', brand='BMW', model='320i')
        typo = catalog_item('b', brand='Bww', model='320i')

        result = normalize_catalog([good, typo])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['brand'], 'BMW')
        self.assertEqual(result[0]['registered_count'], 2)

    def test_brand_separator_only_variants_collapse(self):
        first = catalog_item('a', brand='DeLorean', model='DMC-12')
        second = catalog_item('b', brand='De Lorean', model='DMC-12')

        result = normalize_catalog([first, second])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['registered_count'], 2)

    def test_known_model_typos_are_corrected(self):
        self.assertEqual(model_typo_fix('Skoda', 'Ostavia'), 'Octavia')
        self.assertEqual(model_typo_fix('Skoda', 'OKTAVIA'), 'Octavia')
        self.assertEqual(model_typo_fix('Volkswagen', 'Trasporter'), 'Transporter')
        self.assertEqual(model_typo_fix('Mercedes-Benz', 'Srinter'), 'Sprinter')
        self.assertEqual(model_typo_fix('Toyota', 'Land Gruiser'), 'Land Cruiser')
        self.assertEqual(model_typo_fix('Toyota', 'Corolla'), 'Corolla')

    def test_series_variants_merge_to_shortest_base(self):
        items = [
            catalog_item('a', brand='BMW', model='3'),
            catalog_item('b', brand='BMW', model='3-sarja'),
            catalog_item('c', brand='BMW', model='3er Reihe'),
            catalog_item('d', brand='BMW', model='3ER'),
        ]

        result = normalize_catalog(items)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['model'], '3')
        self.assertEqual(result[0]['registered_count'], 4)

    def test_land_cruiser_series_merge(self):
        first = catalog_item('a', brand='Toyota', model='Land Cruiser (150 Series)')
        second = catalog_item('b', brand='Toyota', model='Land Cruiser 150')

        result = normalize_catalog([first, second])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['model'], 'Land Cruiser 150')
    def test_misspelt_make_prefix_in_model_is_removed(self):
        items = [
            catalog_item('a', brand='Porsche', model='PORCHE 928'),
            catalog_item('b', brand='Porsche', model='928'),
            catalog_item('c', brand='Toyota', model='TOYTA YARIS'),
            catalog_item('d', brand='Toyota', model='Yaris'),
            catalog_item('e', brand='Volkswagen', model='VOLKSVAGEN CRAFTER'),
            catalog_item('f', brand='Volkswagen', model='Crafter'),
        ]

        result = {item['model'] for item in normalize_catalog(items)}

        self.assertEqual(result, {'928', 'Yaris', 'Crafter'})

    def test_glued_and_curated_make_prefixes_are_removed(self):
        self.assertEqual(normalize_model('Eura Mobil', 'EURAMOBIL 595 HB'), '595 HB')
        self.assertEqual(normalize_model('Land Rover', 'LANDROVER DEFENDER 130'), 'DEFENDER 130')
        self.assertEqual(normalize_model('Lynk&Co', 'Lynk & Co 01'), '01')
        self.assertEqual(normalize_model('Lynk&Co', 'LYNK AND CO 02'), '02')
        self.assertEqual(normalize_model('Adria', 'ADRIATIK Coral S 670SL'), 'Coral S 670SL')
        self.assertEqual(normalize_model('Adria', 'ADRIATIK Adria Twin Active'), 'Twin Active')

    def test_make_abbreviation_prefix_in_model_is_removed(self):
        self.assertEqual(normalize_model('Volkswagen', 'VW PASSAT'), 'Passat')
        self.assertEqual(normalize_model('Volkswagen', 'VW Kombi'), 'Kombi')
        self.assertEqual(normalize_model('Mercedes-Benz', 'MB C 220'), 'C 220')
        self.assertEqual(normalize_model('Mercedes-Benz', 'M-B E200 KOMP'), 'E200 KOMP')
        self.assertEqual(normalize_model('Mercedes-Benz', 'MB-HYMER S555'), 'HYMER S555')
        # Another make's chassis reference, BMW's M division and a bare abbreviation stay.
        self.assertEqual(normalize_model('Acbus', 'MB SPRINTER'), 'MB SPRINTER')
        self.assertEqual(normalize_model('Busconcept', 'MB Spinter'), 'MB Spinter')
        self.assertEqual(normalize_model('BMW', 'M 550d xDrive'), 'M 550d xDrive')
        # A model that is nothing but the make abbreviation is not a model name.
        self.assertTrue(model_is_unknown('Volkswagen', 'VW'))
        self.assertTrue(model_is_unknown('Mercedes-Benz', 'MB'))
        self.assertFalse(model_is_unknown('BMW', 'M'))

    def test_make_abbreviation_prefix_no_longer_separates_one_model(self):
        items = [
            catalog_item('a', brand='Volkswagen', model='VW Caddy', variant='X', registered_count=4),
            catalog_item('b', brand='Volkswagen', model='Caddy', variant='X', registered_count=6),
            catalog_item('c', brand='Mercedes-Benz', model='MB Sprinter', variant='Y', registered_count=2),
            catalog_item('d', brand='Mercedes-Benz', model='Sprinter', variant='Y', registered_count=5),
        ]

        result = normalize_catalog(items)

        self.assertEqual({item['model'] for item in result}, {'Caddy', 'Sprinter'})
        self.assertEqual(sorted(item['registered_count'] for item in result), [7, 10])

    def test_make_only_models_stay_hidden(self):
        self.assertTrue(model_is_unknown('Adria', 'Adriatik'))
        self.assertTrue(model_is_unknown('Volvo', 'Volvo'))
        self.assertFalse(model_is_unknown('Hymer', 'Hymermobil 644'))

    def test_displayed_model_drops_repeated_make_without_recasing(self):
        only = catalog_item('a', brand='Eura Mobil', model='EURAMOBIL 635 EB', variant='X')

        result = normalize_catalog([only])

        self.assertEqual(result[0]['model'], '635 EB')
        self.assertEqual(normalize_model('Adria', 'ADRIATIK Vision I_707SL'), 'Vision I_707SL')

    def test_make_like_model_names_are_kept(self):
        self.assertEqual(normalize_model('Mazda', 'MAZDA2 HYBRID'), 'MAZDA2 HYBRID')
        self.assertEqual(normalize_model('Omoda', 'OMODA5 EV'), 'OMODA5 EV')
        self.assertEqual(normalize_model('Seres', 'SERES5'), 'SERES5')
        self.assertEqual(normalize_model('Polestar', 'Polestar2'), 'Polestar2')
        self.assertEqual(normalize_model('Ford', 'Fordson Estate Car 83W'), 'Fordson Estate Car 83W')
        self.assertEqual(normalize_model('Alfa Romeo', 'Alfasud TI'), 'Alfasud TI')
        self.assertEqual(normalize_model('Hymer', 'Hymermobil 644'), 'Hymermobil 644')
        self.assertEqual(normalize_model('Volvo', 'VOLVO(S)'), 'VOLVO(S)')

    def test_misspelt_make_prefix_without_sibling_is_renamed(self):
        self.assertEqual(
            normalize_model('Toyota', 'Toyoyta Land Cruiser (Series)'),
            'Land Cruiser (Series)',
        )
        self.assertEqual(
            normalize_model('Armstrong', 'Armastrong Siddeley Sapphire 234'),
            'Siddeley Sapphire 234',
        )
        self.assertEqual(normalize_model('Toyota', 'Corolla'), 'Corolla')

    def test_model_diacritics_fold(self):
        self.assertEqual(canonical_model_key('Audi', 'TT Coupé'), canonical_model_key('Audi', 'TT Coupe'))
        self.assertEqual(canonical_model_key('Mercedes-Benz', 'Citaro LE MÜ'), canonical_model_key('Mercedes-Benz', 'Citaro LE MU'))

    def test_model_typo_merges_into_one_entry(self):
        good = catalog_item('a', brand='Skoda', model='Octavia', variant='X')
        typo = catalog_item('b', brand='Skoda', model='Ostavia', variant='X')

        result = normalize_catalog([good, typo])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['model'], 'Octavia')
        self.assertEqual(result[0]['registered_count'], 2)

    def test_type_approval_only_duplicates_merge(self):
        first = catalog_item('a', variant='Golf 1.6 TDI (e1*2001/116*0301)', type_approval='e1*2001/116*0301', registered_count=3)
        second = catalog_item('b', variant='Golf 1.6 TDI (e1*2001/116*0302)', type_approval='e1*2001/116*0302', registered_count=4)

        result = normalize_catalog([first, second])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['variant'], 'Golf 1.6 TDI')
        self.assertEqual(result[0]['registered_count'], 7)

    def test_type_approval_difference_with_different_cost_data_merges(self):
        first = catalog_item('a', variant='Golf 1.6 TDI (e1*2001/116*0301)', type_approval='e1*2001/116*0301', co2=110, registered_count=1, source_rank=2)
        second = catalog_item('b', variant='Golf 1.6 TDI (e1*2001/116*0302)', type_approval='e1*2001/116*0302', co2=120, registered_count=4, source_rank=1)

        result = normalize_catalog([first, second])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['variant'], 'Golf 1.6 TDI')
        self.assertEqual(result[0]['registered_count'], 5)
        self.assertEqual(result[0]['co2'], 120)

    def test_validate_catalog_rejects_a_bracketed_variant(self):
        item = catalog_item('a', variant='Golf 1.6 TDI [CO₂ 110 g/km]')

        with self.assertRaises(ValueError):
            validate_catalog([item])

    def test_legacy_variant_detail_suffix_is_stripped_and_merged(self):
        # Shards committed while the builder still appended the `[…]` suffix.
        legacy = catalog_item(
            'a', variant='Golf 1.6 TDI [CO₂ 110 g/km; veromassa 1300 kg]',
            co2=110, registered_count=3, source_rank=2,
        )
        plain = catalog_item('b', variant='Golf 1.6 TDI', co2=120, registered_count=4, source_rank=1)

        result = normalize_catalog([legacy, plain])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['variant'], 'Golf 1.6 TDI')
        self.assertEqual(result[0]['registered_count'], 7)
        self.assertEqual(result[0]['co2'], 120)
        validate_catalog(result)

    def test_variant_detail_strip_keeps_the_visible_power_suffix(self):
        self.assertEqual(strip_variant_detail('Golf 1.6 TDI, 81 kW [CO₂ 110 g/km]'), 'Golf 1.6 TDI, 81 kW')

        first = catalog_item('a', variant='Golf 1.6 TDI, 81 kW', registered_count=3)
        second = catalog_item('b', variant='Golf 2.0 TDI, 110 kW', registered_count=4, source_rank=2)
        result = normalize_catalog([first, second])

        self.assertEqual({item['variant'] for item in result}, {'Golf 1.6 TDI, 81 kW', 'Golf 2.0 TDI, 110 kW'})

    def test_clean_variant_strips_doors_body_and_code_tails(self):
        self.assertEqual(
            clean_variant('INSIGHT Viistoperä (AB) 4ov 1339cm3, 65 kW'),
            'INSIGHT 1.3, 65 kW',
        )
        self.assertEqual(
            clean_variant('GLE 400 d 4MATIC Coupe Farmari (AC) 5ov 2925cm3 A, 243 kW'),
            'GLE 400 d 4MATIC 2.9 A, 243 kW',
        )

    def test_clean_variant_keeps_engine_and_trim_tokens(self):
        # Engine codes, displacement, trims and power must never be stripped.
        self.assertEqual(clean_variant('D-4D, 110 kW'), 'D-4D, 110 kW')
        self.assertEqual(clean_variant('I-PACE, 294 kW'), 'I-PACE, 294 kW')
        self.assertEqual(clean_variant('MX-5, 96 kW'), 'MX-5, 96 kW')
        self.assertEqual(clean_variant('9-3, 110 kW'), '9-3, 110 kW')
        self.assertEqual(clean_variant('quattro, 200 kW'), 'quattro, 200 kW')

    def test_clean_variant_converts_cm3_and_decimal_comma(self):
        self.assertEqual(clean_variant('760i 4ov 5972cm3 A, 400 kW'), '760i 6 A, 400 kW')
        self.assertEqual(clean_variant('CEED 1,6 CRDI ECO SP, 100 kW'), 'CEED 1.6 CRDI ECO SP, 100 kW')

    def test_clean_variant_is_empty_when_only_noise_remains(self):
        self.assertEqual(clean_variant('Farmari (AC) 5ov'), '')
        self.assertEqual(clean_variant('4ov'), '')

    def test_engine_words_are_dropped_from_model_names(self):
        self.assertEqual(strip_engine_words('RAV 4 Hybrid'), 'RAV 4')
        self.assertEqual(strip_engine_words('Mondeo Hybrid'), 'Mondeo')
        self.assertEqual(strip_engine_words('C 220 CDI'), 'C 220')
        self.assertEqual(strip_engine_words('A4 3.0 TDI quattro'), 'A4 3.0 quattro')
        self.assertEqual(strip_engine_words('CLIO (E-Tech Hybrid)'), 'CLIO')
        self.assertEqual(strip_engine_words('A6 50 TFSI e'), 'A6 50')
        self.assertEqual(strip_engine_words('A5 Avant 220kW TFSI e'), 'A5 Avant 220kW')
        self.assertEqual(strip_engine_words('A4 AVANT TDI QUATTRO'), 'A4 AVANT QUATTRO')
        # Emission branding and the second Toyota spelling of its D-4D engine.
        self.assertEqual(strip_engine_words('C 200 Kompressor'), 'C 200')
        self.assertEqual(strip_engine_words('350 G Bluetec'), '350 G')
        self.assertEqual(strip_engine_words('290 GD TURBODIESEL'), '290 GD')
        self.assertEqual(strip_engine_words('RAV 4 D4-D'), 'RAV 4')
        self.assertEqual(strip_engine_words('Avensis D-4D'), 'Avensis')
        self.assertEqual(strip_engine_words('C 200 Compressor'), 'C 200')
        self.assertEqual(strip_engine_words('E 200 Komp'), 'E 200')
        self.assertEqual(strip_engine_words('V70 Flexifuel'), 'V70')
        self.assertEqual(strip_engine_words('Transit 350L Cng'), 'Transit 350L')
        # A hyphenated compound descriptor and Audi's model-line name are kept.
        self.assertEqual(strip_engine_words('CNG-Technik'), 'CNG-Technik')
        self.assertEqual(strip_engine_words('A3 Sportback e-tron'), 'A3 Sportback e-tron')
        self.assertEqual(strip_engine_words('e-tron GT'), 'e-tron GT')
        # Digits, trims and drivetrain badges are never engine wording.
        self.assertEqual(strip_engine_words('Mazda 6'), 'Mazda 6')
        self.assertEqual(strip_engine_words('Peugeot 307'), 'Peugeot 307')
        self.assertEqual(strip_engine_words('911'), '911')
        self.assertEqual(strip_engine_words('320d'), '320d')
        self.assertEqual(strip_engine_words('Golf GTI'), 'Golf GTI')
        self.assertEqual(strip_engine_words('Cooper S'), 'Cooper S')
        self.assertEqual(strip_engine_words('ID.4 PRO 150 kW'), 'ID.4 PRO 150 kW')
        # A name that is nothing but engine wording is kept as is.
        self.assertEqual(strip_engine_words('Hybrid'), 'Hybrid')

    def test_body_words_are_dropped_from_model_names(self):
        self.assertEqual(strip_body_words('A3 Sportback'), 'A3')
        self.assertEqual(strip_body_words('A4 Avant'), 'A4')
        self.assertEqual(strip_body_words('Golf Variant'), 'Golf')
        self.assertEqual(strip_body_words('Octavia Kombi'), 'Octavia')
        self.assertEqual(strip_body_words('Astra Sports Tourer'), 'Astra')
        self.assertEqual(strip_body_words('Astra Station Wagon'), 'Astra')
        self.assertEqual(strip_body_words('Accord Tourer'), 'Accord')
        self.assertEqual(strip_body_words('Insignia Sports Tourer SW'), 'Insignia')
        self.assertEqual(strip_body_words('Golf Farmari'), 'Golf')
        self.assertEqual(strip_body_words('Astra Viistoperä'), 'Astra')
        # A name that is nothing but a body word is kept as is.
        self.assertEqual(strip_body_words('Kombi'), 'Kombi')
        self.assertEqual(strip_body_words('Variant'), 'Variant')
        # Trims and ambiguous body-as-model words are never stripped.
        self.assertEqual(strip_body_words('Golf GTI'), 'Golf GTI')
        self.assertEqual(strip_body_words('Cooper S'), 'Cooper S')
        self.assertEqual(strip_body_words('TT Coupe'), 'TT Coupe')
        self.assertEqual(strip_body_words('A5 Cabriolet'), 'A5 Cabriolet')
        self.assertEqual(strip_body_words('Combo Van'), 'Combo Van')
        self.assertEqual(strip_body_words('Ranger Pickup'), 'Ranger Pickup')

    def test_visible_body_matches_the_picker_labels(self):
        self.assertEqual(visible_body('AB'), 'Viistoperä')
        self.assertEqual(visible_body('AC'), 'Farmari')
        self.assertEqual(visible_body('BB'), 'Pakettiauto')
        self.assertEqual(visible_body('SA'), 'Matkailuauto')
        self.assertEqual(visible_body(''), '')
        self.assertEqual(visible_body('CA'), '')  # bus: no body suffix

    def test_body_variants_stay_separate_versions(self):
        hatch = catalog_item('source-a', model='A3 Sportback', body_type='AB')
        estate = catalog_item('source-b', model='A3 Sportback', body_type='AC')

        result = normalize_catalog([hatch, estate])

        self.assertEqual(len(result), 2)
        self.assertEqual({item['body_type'] for item in result}, {'AB', 'AC'})
        self.assertEqual({item['model'] for item in result}, {'A3'})

    def test_pickup_body_codes_share_one_visible_option(self):
        flat = catalog_item('source-a', model='Ranger', body_type='BA', vehicle_type='pickup')
        pick = catalog_item('source-b', model='Ranger', body_type='BE', vehicle_type='pickup')

        result = normalize_catalog([flat, pick])

        self.assertEqual(len(result), 1)

    def test_engine_only_model_names_are_unknown(self):
        self.assertTrue(model_is_unknown('MG', 'Electric'))
        self.assertTrue(model_is_unknown('MG', 'Hybrid'))
        self.assertTrue(model_is_unknown('Mercedes-Benz', 'Kompressor'))
        self.assertFalse(model_is_unknown('MG', 'MG4 Electric'))
        self.assertFalse(model_is_unknown('Volvo', 'V60'))

    def test_engine_wording_no_longer_separates_one_model(self):
        items = [
            catalog_item('a', brand='Toyota', model='Rav4', variant='X', registered_count=10),
            catalog_item('b', brand='Toyota', model='RAV 4', variant='X', registered_count=10),
            catalog_item('c', brand='Toyota', model='RAV 4 Hybrid', variant='X', registered_count=10),
        ]

        result = normalize_catalog(items)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['model'], 'Rav4')
        self.assertEqual(result[0]['registered_count'], 30)

    def test_emission_branding_no_longer_separates_one_model(self):
        items = [
            catalog_item('a', brand='Mercedes-Benz', model='C 200 Kompressor', variant='X', registered_count=3),
            catalog_item('b', brand='Mercedes-Benz', model='C 200', variant='X', registered_count=7),
        ]

        result = normalize_catalog(items)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['model'], 'C 200')
        self.assertEqual(result[0]['registered_count'], 10)

    def test_curated_truncation_alias_merges_rav_into_rav4(self):
        self.assertEqual(model_typo_fix('Toyota', 'Rav'), 'Rav4')
        items = [
            catalog_item('a', brand='Toyota', model='Rav', variant='X', registered_count=4),
            catalog_item('b', brand='Toyota', model='RAV4', variant='X', registered_count=6),
        ]

        result = normalize_catalog(items)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['model'], 'Rav4')
        self.assertEqual(result[0]['registered_count'], 10)

    def test_legitimate_trim_variants_stay_separate(self):
        base = catalog_item('a', brand='Mini', model='Cooper S')
        other = catalog_item('b', brand='Mini', model='Cooper D')

        result = normalize_catalog([base, other])

        self.assertEqual(len(result), 2)
        self.assertEqual({item['model'] for item in result}, {'Cooper S', 'Cooper D'})

    def test_unknown_models_are_detected(self):
        self.assertTrue(model_is_unknown('Audi', 'Audi'))
        self.assertTrue(model_is_unknown('Toyota', '-'))
        self.assertTrue(model_is_unknown('Peugeot', ''))
        self.assertFalse(model_is_unknown('Audi', 'A4'))
        self.assertFalse(model_is_unknown('Mercedes-Benz', 'C 220 CDI'))

    def test_designation_models_are_detected(self):
        self.assertTrue(model_is_designation('5D PASSAT VARIANT 1.9TDI-3B/271', '5D PASSAT VARIANT 1.9TDI-3B/271, 66 kW (e1*2001/116*0301)'))
        self.assertTrue(model_is_designation('4ov 1898cm3 A', '4ov 1898cm3 A, 120 kW'))
        self.assertTrue(model_is_designation('4D SEDAN C 180-202018/269', '4D SEDAN C 180-202018/269, 90 kW'))
        self.assertFalse(model_is_designation('Passat', '5D PASSAT VARIANT 1.9TDI-3BG/269, 74 kW'))
        self.assertFalse(model_is_designation('Corolla', 'COROLLA Farmari (AC) 4ov 1798cm3, 72 kW (e6*2001/116*0148)'))
        self.assertFalse(model_is_designation('Golf', 'GOLF Farmari (AC) 4ov 1968cm3, 103 kW'))

    def test_technical_designations_are_detected(self):
        self.assertTrue(model_is_technical('4ov 1898cm3 A'))
        self.assertTrue(model_is_technical('Viistoperä (AB) 4ov 1360cm3'))
        self.assertTrue(model_is_technical('112 CDI'))
        self.assertTrue(model_is_technical('5D STW V70 2.5-LW51/266'))
        self.assertTrue(model_is_technical('12000cm3 A'))
        self.assertFalse(model_is_technical('Passat'))
        self.assertFalse(model_is_technical('C 220 Cdi'))
        self.assertFalse(model_is_technical('ID.4 PRO 150 kW'))
        self.assertFalse(model_is_technical('Q5 50 TFSI e'))
        self.assertFalse(model_is_technical('Mazda 6'))
        self.assertFalse(model_is_technical('911'))
        self.assertFalse(model_is_technical('Kombi'))


class SelectableModelTests(unittest.TestCase):
    """A Malli entry is hidden only when it is BOTH rare and old."""

    def picker(self, items):
        return {(brand, model) for brand, model, _ in selectable_models(items)}

    def brands(self, items):
        return {brand for brand, _, _ in selectable_models(items)}

    def test_year_span_parsing(self):
        self.assertEqual(model_year_span('1998–2005'), (1998, 2005))
        self.assertEqual(model_year_span('2020-2024'), (2020, 2024))
        self.assertEqual(model_year_span('2005'), (2005, 2005))
        self.assertEqual(model_year_span('Tuntematon'), (None, None))
        self.assertEqual(model_year_span('9999–0'), (None, None))
        self.assertEqual(normalize_years('Tuntematon'), 'Tuntematon')
        self.assertEqual(normalize_years('1998–2005'), '1998–2005')

    def test_rare_and_obsolete_helpers(self):
        self.assertTrue(model_is_rare(MIN_MODEL_REGISTRATIONS - 1))
        self.assertFalse(model_is_rare(MIN_MODEL_REGISTRATIONS))
        self.assertTrue(model_is_obsolete(None))
        self.assertTrue(model_is_obsolete(MIN_MODEL_YEAR - 1))
        self.assertFalse(model_is_obsolete(MIN_MODEL_YEAR))

    def test_rare_and_old_model_is_hidden(self):
        items = [
            catalog_item('a', brand='Volvo', model='240', years='1985', registered_count=1),
            catalog_item('b', brand='Volvo', model='V70', years='2005', registered_count=300),
        ]

        self.assertEqual(self.picker(items), {('Volvo', 'V70')})

    def test_rare_but_modern_model_is_kept(self):
        items = [
            catalog_item('a', brand='Ferrari', model='296 GTB', years='2023', registered_count=1),
            catalog_item('b', brand='Ferrari', model='Roma', years='2020', registered_count=2),
        ]

        self.assertEqual(self.picker(items), {('Ferrari', '296 GTB'), ('Ferrari', 'Roma')})

    def test_popular_classic_is_kept(self):
        items = [catalog_item('a', brand='Volvo', model='240', years='1985', registered_count=250)]

        self.assertEqual(self.picker(items), {('Volvo', '240')})

    def test_newest_year_of_the_span_decides(self):
        items = [
            catalog_item('a', brand='Ford', model='Escort', years='1988–1994', registered_count=1),
            catalog_item('b', brand='Ford', model='Focus', years='2005', registered_count=10),
        ]

        self.assertEqual(self.picker(items), {('Ford', 'Escort'), ('Ford', 'Focus')})

    def test_model_without_usable_year_is_hidden_when_rare_and_cascades_to_the_make(self):
        items = [
            catalog_item('a', brand='Horch', model='853', years='Tuntematon', registered_count=1),
            catalog_item('b', brand='Horch', model='930', years='Tuntematon', registered_count=1),
        ]

        self.assertEqual(self.picker(items), set())
        self.assertEqual(self.brands(items), set())

    def test_model_without_usable_year_is_kept_when_common(self):
        items = [catalog_item('a', brand='Saab', model='900', years='Tuntematon', registered_count=50)]

        self.assertEqual(self.picker(items), {('Saab', '900')})

    def test_validate_index_rejects_a_hidden_model(self):
        items = [
            catalog_item('a', brand='Volvo', model='240', years='1985', registered_count=1),
            catalog_item('b', brand='Volvo', model='V70', years='2005', registered_count=300),
        ]
        models = selectable_models(items)
        index = {
            'count': len(items),
            'brands': ['Volvo'],
            'vehicleTypes': ['passenger'],
            'models': [
                {
                    'brand': 'Volvo',
                    'model': 'V70',
                    'vehicle_type': 'passenger',
                    'powertrains': ['diesel'],
                }
            ],
            'availability': {'Volvo': {'passenger': ['diesel']}},
        }

        validate_index(index, items, models)

        index['models'].append(
            {
                'brand': 'Volvo',
                'model': '240',
                'vehicle_type': 'passenger',
                'powertrains': ['diesel'],
            }
        )
        with self.assertRaises(ValueError):
            validate_index(index, items, models)

    def test_model_powertrains_are_aggregated_per_row(self):
        items = [
            catalog_item('a', brand='Toyota', model='Corolla', powertrain='petrol', registered_count=50),
            catalog_item('b', brand='Toyota', model='Corolla', powertrain='hybrid', registered_count=40),
            catalog_item('c', brand='Toyota', model='Corolla', vehicle_type='van', powertrain='diesel', registered_count=10),
        ]

        models = selectable_models(items)

        self.assertEqual(models[('Toyota', 'Corolla', 'passenger')], ('hybrid', 'petrol'))
        self.assertEqual(models[('Toyota', 'Corolla', 'van')], ('diesel',))
        self.assertEqual(
            powertrain_availability(models),
            {'Toyota': {'passenger': ['hybrid', 'petrol'], 'van': ['diesel']}},
        )


if __name__ == '__main__':
    unittest.main()