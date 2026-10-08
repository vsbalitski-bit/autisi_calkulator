# Autosi Kululaskuri

WordPress-plugin for estimating annual car costs in Finland.

**Plugin version:** 0.5.0 · **Bundled catalogue:** 2026.10.04.3 (Traficom open data, 30 June 2026)

## Install

1. Copy this directory to `wp-content/plugins/autosi-kululaskuri`.
2. Activate **Autosi Kululaskuri** in WordPress.
3. Add `[autosi_kululaskuri]` to a page or post.
4. Adjust the editable default prices at **Settings → Autosi Kululaskuri**.

## Included calculation areas

- fuel, electricity, and charging losses;
- home/public charging mix and a winter-consumption factor;
- Finnish annual vehicle-tax estimate;
- insurance, maintenance, roadworthiness-inspection reserve, tyres, and repair reserve;
- optional depreciation;
- comparison of up to ten cars.

The editable default prices for petrol, diesel, and electricity use Traficom's published comparison-price input values for 1 April–30 June 2026. Public-charging cost remains a configurable market estimate because Traficom notes that a national public-charging price feed is not yet available.

The bundled catalogue contains 483,202 selectable configurations across 338 normalized makes and 17,764 make/model/type combinations from Traficom's 30 June 2026 open-data release. Repeated registrations are aggregated; identical calculator configurations are merged — a pair of rows that differs only by its Traficom type-approval code counts as identical, because the picker never shows that code, and rows that would read the same in the version list are merged even when a cost-driving value (CO₂, mass, or consumption) differs; the most registered raw variant supplies the recorded values. Makes are deduplicated across abbreviations, legal-form suffixes and chassis+converter composites (`MB`/`M-B`/`Mercedes-Benz-Dethleffs` → `Mercedes-Benz`, `Bürstner GmbH` → `Bürstner`), and human data-entry typos are corrected against a hand-curated list (`Bww` → `BMW`, `Volswagen` → `Volkswagen`, `Hundai` → `Hyundai`, `Garthago` → `Carthago`; `BRAND_TYPO_ALIASES` in `tools/build_traficom_catalog.py`). Duplicate model spellings — including diacritic variants such as `Coupé`/`Coupe` — are collapsed to one spelling, and hand-curated model misspellings are corrected (`Ostavia` → `Octavia`, `Trasporter` → `Transporter`, `Srinter` → `Sprinter`, `Land Gruiser` → `Land Cruiser`; `MODEL_TYPO_ALIASES` in `tools/build_traficom_catalog.py`). Series wording is folded too, so `3`/`3-sarja`/`3ER`/`3er Reihe`, `5`/`5 Sarja`/`5er Reihe`, `62`/`62 Series`/`Series 62`, `600`/`600 SERIES` and `Land Cruiser 150`/`Land Cruiser (150 Series)` each show up once, keeping the shortest base spelling. Engine and powertrain wording is dropped from the model name as well — the version (`Moottori / käyttövoima`) field carries the engine — so `RAV 4 Hybrid`, `RAV 4` and `Rav4` are one Malli entry and `C 220 CDI`/`C 220 DIESEL` become `C 220` (`MODEL_ENGINE_WORDS_RE` in `tools/build_traficom_catalog.py`; digits, trims and drivetrain badges such as `Mazda 6`, `Golf GTI` and `quattro` are preserved, and a name consisting only of engine wording is treated as unknown). A repeated make at the start of the model is dropped as well (`PORCHE 928` → `928`, `Mercedez-Benz C 320` → `C 320`, `TOYTA YARIS` → `Yaris`, `LANDROVER DEFENDER 130` → `DEFENDER 130`, `Lynk & Co 01` → `01`, `ADRIATIK Coral S 670SL` → `Coral S 670SL`), while genuine names that merely start like the make are preserved (`Mazda2`, `OMODA5 EV`, `Fordson`, `Alfasud`, `Hymermobil`). Placeholder models that only repeat the make are hidden, and non-make placeholders (`Ks. Huom.`, `Övriga`, `Omavalmiste`, `V-series 60 SP`) are dropped from the make picker. A make is offered only while it still has at least one selectable model, and a Malli entry is hidden when it is BOTH a one-off (fewer than two registered vehicles in the whole catalogue) and obsolete (newest first-registration year before 1990, or no usable year at all) — the vehicles stay in the data, so the totals are unchanged. Raw Traficom technical designations that carry engine/body/approval data are kept out of the Malli list too — the engine already appears in the following field. This covers two groups: rows where the model was the `mallimerkinta` fallback (detected because the variant's base then equals the model, e.g. `5D PASSAT VARIANT 1.9TDI-3B/271`, `4ov 1898cm3 A`) and values that look technical (door codes `2D/4D/5D`, displacement `1.8/2,0`, `cm3`, approval tails `-3B/271` or `-638094`). Makes left without any selectable model are dropped. Future raw-source builds retain merged source IDs and type/variant/version identifiers in `source_records`; identifiers already collapsed in the prior generated snapshot cannot be recovered without the original Traficom ZIP. The source is licensed under CC BY 4.0. Technical fields such as variant/version IDs, powertrain, CO₂, mass, power, and registration period come from Traficom. Fuel/energy-consumption and service-cost defaults are calculation estimates because those exact cost fields are not present in that data release.

The reproducible build is a two-stage pipeline: run `tools/build_traficom_catalog.py` with `traficom_vehicles_2026.zip` in `/tmp`, then run `tools/enrich_catalog_with_eea.py` before packaging. The first stage preserves individual type approvals so EEA matching happens before calculator-equivalent variants are merged. Do not publish the intermediate shards between these stages. Both stages deliberately discard registration marks, VINs, municipalities, and odometer readings. The currently bundled snapshot has 55,939 EEA official WLTP matches; variants outside EEA coverage retain an explicitly labelled CO₂-derived/default estimate. Runtime data is stored in 256 gzip-compressed shards; only makes are sent on initial page load, and the picker narrows on demand through public REST routes — `/catalog/filters` returns which makes still have a model for the chosen vehicle type and fuel, plus the fuels and vehicle types that have data — each list is narrowed only by the fields that precede it in the form, so choosing a value never resets that field, `/catalog/models` the models of a make for the chosen type and fuel, and `/catalog/vehicles` the versions of a model. The bundled index therefore records the available powertrain codes per make/model/type (`powertrains`) plus a compact `availability` map, so choosing a fuel hides makes and models without a matching version instead of only reporting an empty list.

## CSV columns

Required columns: `id,brand,model,powertrain`. Optional: `variant,years,vehicle_type,vehicle_class,body_type,seats,mass_source,tax_measurement,tax_power_source,fuel_consumption,electric_consumption,co2,mass,tax_mass,road_mass,technical_mass,curb_mass,service_cost,service_interval_km,service_interval_months,source,consumption_source,service_source,data_status,type_approval,variant_code,version_code,source_rank,registered_count`.

Allowed `powertrain` values: `petrol`, `diesel`, `hybrid`, `phev`, `electric`.

Administrator CSV imports are capped at 20 MiB and 250,000 rows. The selectable index (brands, models, vehicle types) is precomputed at import time, so page renders and REST calls never scan the full imported catalog.

The `vehicle_type` column accepts `passenger`, `light_truck`, `minibus`, `van`, `motorhome`, `bus`, `special`, or `pickup`. When omitted, an imported vehicle is treated as a passenger car. `vehicle_class` accepts `M1`, `M1G`, `N1`, `N1G`, `M2`, `M2G`, `M3`, `M3G`, or an empty value. Of the mass fields, `tax_mass` is the road-legal taxable mass — not the technical maximum mass.

The bundled catalogue derives types from Traficom's official vehicle class, vehicle group (`ajoneuvoryhma`) and body-type (`korityyppi`) codes: 393,087 passenger cars, 50,614 vans, 32,230 light trucks, 33,634 motorhomes, 4,247 buses, 2,979 pickups, 1,521 minibuses, and 3,245 special-purpose vehicles. Invalid/missing registration years display as `Tuntematon`; the inspection reserve then uses a conservative annual estimate. The source builder covers vehicle classes M1, M1G, N1, N1G, M2, M2G, M3 and M3G, so vans, light trucks, buses and motorhomes are all selectable from the bundled catalogue.

## Data confidence

The calculator shows each selected version's source level before calculation: Traficom open technical data, official EEA WLTP data when matched, or an editable public calculation estimate. Vehicle tax is labelled an estimate when CO₂ is missing/out of range, mass is implausible, or an electric vehicle's exact first-use date is unknown. See [DATA_SOURCES.md](DATA_SOURCES.md) for the source policy and limitations.

The 2026 vehicle-tax calculation uses the current Traficom WLTP/NEDC tables and power-tax rates. For an electric car, enter the exact first-use date in detailed mode because the basic-tax rate changes at 30 September 2021.

## Catalogue updates

The raw-source build uses `tools/build_traficom_catalog.py`. `tools/rebuild_traficom_catalog.py` can normalize and rebuild the checked-in generated snapshot when the original Traficom ZIP is unavailable. The bundled catalogue updates automatically only when it is still the bundled catalogue. A CSV import is preserved as administrator-managed data; the settings page offers a deliberate reset to the bundled catalogue.
