( function () {
	'use strict';

	const config = window.AutosiKululaskuri;
	if ( ! config ) return;

	/**
	 * Wire up one calculator instance. Runs once per [data-component="autosi-kululaskuri"]
	 * root so a page can host several calculators (e.g. two shortcodes) independently.
	 */
	function initCalculator( root ) {
		const form = root.querySelector( '.ak-form' );
		if ( ! form ) return;
		const fields = form.elements;
		const t = config.i18n || {};
		const locale = config.locale || 'fi-FI';
		const euro = new Intl.NumberFormat( locale, { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 } );
		const euroPrecise = new Intl.NumberFormat( locale, { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 } );
		const int = new Intl.NumberFormat( locale );
		let mode = 'simple';
		let selected = null;
		let selectedVehicles = [];
		let modelRequest = 0;
		let vehicleRequest = 0;
		let filterRequest = 0;
		let availableBrands = null;
		let availablePowertrains = null;
		let availableTypes = null;
		let brandDroppedForFuel = false;
		let comparisons = [];

		const typeLabels = t.typeLabels || { petrol: 'Bensiini', diesel: 'Diesel', hybrid: 'Täyshybridi', phev: 'Lataushybridi', electric: 'Sähkö' };
		const number = value => Math.max( 0, Number( value ) || 0 );
		const money = value => euro.format( value );
		const moneyExact = value => euroPrecise.format( value );
		// Minimal printf for the %s / %1$s placeholders used in the PHP i18n strings.
		const sprintf = ( format, ...args ) => {
			let sequential = 0;
			return String( format ).replace( /%(\d+)\$s|%s/g, ( match, position ) => {
				const value = position ? args[ Number( position ) - 1 ] : args[ sequential++ ];
				return value === undefined || value === null ? '' : String( value );
			} );
		};
		const cleanVariant = car => {
			let value = String( car && car.variant || '' );
			const approval = car && car.type_approval;
			if ( approval ) value = value.split( ` (${ approval })` ).join( '' );
			return value.replace( /\s{2,}/g, ' ' ).trim();
		};

		function hideStaleResults() {
			root.querySelector( '.ak-results' ).hidden = true;
			root.querySelector( '.ak-comparison-assumptions' ).classList.remove( 'has-differences' );
		}

		function fillSelect( select, values, placeholder, disableWhenEmpty = true ) {
			select.innerHTML = `<option value="">${ placeholder }</option>` + values.map( value => `<option value="${ escapeHtml( value.value ) }">${ escapeHtml( value.label ) }</option>` ).join( '' );
			select.disabled = disableWhenEmpty && ! values.length;
		}

		function escapeHtml( value ) {
			return String( value ).replace( /[&<>'"]/g, c => ( { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;' }[ c ] ) );
		}

		const catalogBrands = config.catalogIndex.brands || [];
		const catalogBrandTypes = config.catalogIndex.brandTypes || {};

		/**
		 * Makes still compatible with the chosen vehicle type and fuel. The server list is
		 * exact; while it is missing (request failed, or a catalogue without powertrain data)
		 * fall back to the bundled make/type map.
		 */
		function brandOptions() {
			const vehicleType = fields.vehicleType.value;
			if ( Array.isArray( availableBrands ) ) {
				return availableBrands.map( brand => ( { value: brand, label: brand } ) );
			}
			const brands = vehicleType ? catalogBrands.filter( brand => ( catalogBrandTypes[ brand ] || [] ).includes( vehicleType ) ) : catalogBrands;
			return brands.map( brand => ( { value: brand, label: brand } ) );
		}

		function setBrands() {
			const previous = fields.brand.value;
			const options = brandOptions();
			const emptyLabel = fields.powertrain.value ? ( t.brandPlaceholderEmptyFuel || t.brandPlaceholderEmpty ) : t.brandPlaceholderEmpty;
			fillSelect( fields.brand, options, options.length ? t.brandPlaceholder : emptyLabel );
			// Rebuilding the options resets the select, so the current choice has to be restored:
			// the picker keeps it unless the narrowed list no longer offers it.
			const kept = options.some( option => option.value === previous );
			fields.brand.value = kept ? previous : '';
			brandDroppedForFuel = Boolean( previous ) && ! kept && Boolean( fields.powertrain.value );
		}

		/** Keep the template's "any fuel" label so it stays translated. */
		function powertrainAnyLabel() {
			const first = fields.powertrain.options[ 0 ];
			return first && ! first.value ? first.textContent : '';
		}

		/** Fuels that still have data for the chosen vehicle type. */
		function powertrainOptions() {
			const codes = Array.isArray( availablePowertrains ) && availablePowertrains.length ? availablePowertrains : Object.keys( typeLabels );
			return codes.map( code => ( { value: code, label: typeLabels[ code ] || code } ) );
		}

		function setPowertrains() {
			const previous = fields.powertrain.value;
			const options = powertrainOptions();
			fillSelect( fields.powertrain, options, powertrainAnyLabel(), false );
			// See setBrands(): the rebuild resets the select, so re-apply the current choice.
			fields.powertrain.value = options.some( option => option.value === previous ) ? previous : '';
		}

		/** Vehicle types that still have data for the chosen fuel. */
		function setVehicleTypes() {
			const types = Array.isArray( availableTypes ) ? availableTypes : ( config.catalogTypes || [] );
			Array.from( fields.vehicleType.options ).forEach( option => {
				if ( ! option.value ) return;
				if ( option.dataset.label === undefined ) option.dataset.label = option.textContent;
				const current = fields.vehicleType.value === option.value;
				const hasData = types.includes( option.value );
				option.disabled = ! hasData && ! current;
				option.textContent = hasData || current ? option.dataset.label : option.dataset.label + ' ' + t.noDataType;
			} );
		}

		/**
		 * Ask the catalogue which makes, fuels and vehicle types are still valid for the
		 * current selection, then rebuild every select so non-matching values disappear.
		 */
		async function refreshFilters() {
			const request = ++filterRequest;
			let filters = null;
			try {
				const url = new URL( config.filtersUrl );
				if ( fields.vehicleType.value ) url.searchParams.set( 'vehicle_type', fields.vehicleType.value );
				if ( fields.powertrain.value ) url.searchParams.set( 'powertrain', fields.powertrain.value );
				const response = await fetch( url );
				if ( ! response.ok ) throw new Error( 'Catalog filter request failed' );
				const payload = await response.json();
				filters = payload && typeof payload === 'object' ? payload : null;
			} catch ( error ) {
				filters = null;
			}
			if ( request !== filterRequest ) return;
			availableBrands = filters && Array.isArray( filters.brands ) ? filters.brands : null;
			availablePowertrains = filters && Array.isArray( filters.powertrains ) ? filters.powertrains : null;
			availableTypes = filters && Array.isArray( filters.vehicleTypes ) ? filters.vehicleTypes : null;
			setVehicleTypes();
			setPowertrains();
			setBrands();
		}

		function initSelects() {
			setVehicleTypes();
			setBrands();
			[ 'petrolPrice', 'dieselPrice', 'insurance', 'homePrice', 'publicPrice' ].forEach( name => { fields[ name ].value = config.settings[ { petrolPrice: 'petrol_price', dieselPrice: 'diesel_price', insurance: 'insurance', homePrice: 'home_electricity', publicPrice: 'public_electricity' }[ name ] ]; } );
		}

		async function setModels() {
			const request = ++modelRequest;
			const brand = fields.brand.value;
			const vehicleType = fields.vehicleType.value;
			const powertrain = fields.powertrain.value;
			const previousModel = fields.model.value;
			vehicleRequest++;
			selectedVehicles = [];
			selected = null;
			fields.firstUseDate.value = '';
			root.querySelector( '.ak-model-note' ).textContent = ! brand && brandDroppedForFuel ? t.brandDroppedForFuel : t.startPrompt;
			fillSelect( fields.model, [], brand ? t.loadingModels : t.modelPlaceholder );
			fillSelect( fields.vehicle, [], t.versionPlaceholder );
			hideStaleResults();
			renderDataQuality();
			if ( ! brand ) return;
			const url = new URL( config.modelsUrl );
			url.searchParams.set( 'brand', brand );
			url.searchParams.set( 'vehicle_type', vehicleType );
			url.searchParams.set( 'powertrain', powertrain );
			try {
				const response = await fetch( url );
				if ( ! response.ok ) throw new Error( 'Catalog model request failed' );
				const models = await response.json();
				if ( request !== modelRequest || brand !== fields.brand.value || vehicleType !== fields.vehicleType.value || powertrain !== fields.powertrain.value ) return;
				if ( ! models.length ) {
					const supportedTypes = config.catalogTypes || [];
					root.querySelector( '.ak-model-note' ).textContent = powertrain ? t.noModelsForFuel : vehicleType ? ( supportedTypes.includes( vehicleType ) ? t.noModelsForType : t.vehicleTypeUnavailable ) : t.noModelsOption;
				}
				fillSelect( fields.model, models.map( model => ( { value: model, label: model } ) ), models.length ? t.modelPlaceholder : t.noModelsOption );
				// A narrower fuel or type can keep the current model valid; reload its versions.
				if ( previousModel && models.includes( previousModel ) ) {
					fields.model.value = previousModel;
					setVehicles();
				}
			} catch ( error ) {
				if ( request !== modelRequest ) return;
				fillSelect( fields.model, [], t.modelPlaceholder );
				root.querySelector( '.ak-model-note' ).textContent = t.catalogError;
			}
		}

		/** Label of a vehicle type as the template renders it (no extra i18n needed). */
		function vehicleTypeLabel( code ) {
			const option = Array.from( fields.vehicleType.options ).find( item => item.value === code );
			return option ? ( option.dataset.label || option.textContent ) : code;
		}

		async function setVehicles() {
			const request = ++vehicleRequest;
			const brand = fields.brand.value;
			const model = fields.model.value;
			const vehicleType = fields.vehicleType.value;
			const powertrain = fields.powertrain.value;
			selectedVehicles = [];
			selected = null;
			fields.firstUseDate.value = '';
			fillSelect( fields.vehicle, [], t.loadingVersions );
			hideStaleResults();
			renderDataQuality();
			if ( ! brand || ! model ) {
				fillSelect( fields.vehicle, [], t.versionPlaceholder );
				return;
			}
			const url = new URL( config.vehiclesUrl );
			url.searchParams.set( 'brand', brand );
			url.searchParams.set( 'model', model );
			url.searchParams.set( 'vehicle_type', vehicleType );
			url.searchParams.set( 'powertrain', powertrain );
			try {
				const response = await fetch( url );
				if ( ! response.ok ) throw new Error( 'Catalog request failed' );
				const cars = await response.json();
				if ( request !== vehicleRequest || brand !== fields.brand.value || model !== fields.model.value || vehicleType !== fields.vehicleType.value || powertrain !== fields.powertrain.value ) return;
				selectedVehicles = cars;
				// The catalogue merges every row that reads the same, so a label is unique —
				// except when no type filter is chosen: the same text can then describe a car
				// registered in two classes (passenger vs van), which the type name separates.
				const typeSuffix = car => fields.vehicleType.value || ! car.vehicle_type ? '' : ` · ${ vehicleTypeLabel( car.vehicle_type ) }`;
				const versionOptions = cars.map( car => ( {
					value: car.id,
					label: `${ typeLabels[ car.powertrain ] || car.powertrain } · ${ cleanVariant( car ) } · ${ car.years }${ typeSuffix( car ) }`
				} ) ).sort( ( a, b ) => a.label.localeCompare( b.label, locale, { sensitivity: 'base' } ) );
				fillSelect( fields.vehicle, versionOptions, t.versionPlaceholder );
				if ( ! cars.length && powertrain ) {
					root.querySelector( '.ak-model-note' ).textContent = t.noVersionsForFuel;
				}
			} catch ( error ) {
				if ( request !== vehicleRequest ) return;
				fillSelect( fields.vehicle, [], t.versionPlaceholder );
				root.querySelector( '.ak-model-note' ).textContent = t.catalogError;
			}
		}

		function selectVehicle() {
			const nextSelected = selectedVehicles.find( car => car.id === fields.vehicle.value ) || null;
			if ( selected && nextSelected && selected.id !== nextSelected.id ) fields.firstUseDate.value = '';
			selected = nextSelected;
			hideStaleResults();
			updateFieldVisibility();
			root.querySelector( '.ak-phev-only' ).hidden = ! selected || selected.powertrain !== 'phev';
			if ( selected ) {
				fields.fuelConsumption.value = selected.fuel_consumption;
				fields.electricConsumption.value = selected.electric_consumption;
				fields.vehicleTax.value = Math.round( vehicleTax( selected, fields.firstUseDate.value ) );
				fields.serviceCost.value = selected.service_cost;
				fields.serviceIntervalKm.value = selected.service_interval_km;
				fields.serviceIntervalMonths.value = selected.service_interval_months;
			}
			const consumptionNote = selected && selected.consumption_source && selected.consumption_source.startsWith( 'EEA' ) ? t.consumptionEea : t.consumptionEstimate;
			root.querySelector( '.ak-model-note' ).textContent = selected ? sprintf( t.techDataNote, consumptionNote, selected.brand, selected.model, cleanVariant( selected ), selected.years ) : t.startPrompt;
			renderDataQuality();
		}

		function renderDataQuality() {
			const panel = root.querySelector( '[data-result="dataQuality"]' );
			if ( ! selected ) {
				panel.hidden = true;
				panel.innerHTML = '';
				return;
			}
			const officialConsumption = String( selected.consumption_source || '' ).startsWith( 'EEA' );
			const serviceIsVerified = /official|manufacturer|VIN/i.test( String( selected.service_source || '' ) ) && !/required/i.test( String( selected.service_source || '' ) );
			const electricFirstUseIsExact = selected.powertrain !== 'electric' || ( mode === 'detailed' && Boolean( fields.firstUseDate.value ) );
			const vehicleClass = selected.vehicle_class || 'M1';
			const isBus = [ 'M2', 'M2G', 'M3', 'M3G' ].includes( vehicleClass );
			const isVanClass = [ 'N1', 'N1G' ].includes( vehicleClass );
			const hasLegalTaxMass = selected.vehicle_class ? number( selected.tax_mass ) > 0 && selected.mass_source === 'road_traffic' : number( selected.mass ) > 0;
			const taxMassIsPlausible = hasLegalTaxMass && number( selected.tax_mass ?? selected.mass ) >= 500 && number( selected.tax_mass ?? selected.mass ) <= 50000;
			const taxCo2IsPlausible = number( selected.co2 ) > 0 && number( selected.co2 ) <= 500;
			const firstYear = vehicleStartYear( selected );
			const massForTax = number( selected.tax_mass ?? selected.mass );
			const co2TaxThreshold = isVanClass ? 2008 : massForTax <= 2500 ? 2001 : 2002;
			const needsMassTaxTable = ! firstYear || firstYear < co2TaxThreshold || ! taxCo2IsPlausible;
			const taxInputsAreReliable = isBus || ( ! isVanClass && taxMassIsPlausible && ( selected.powertrain === 'electric' ? electricFirstUseIsExact : taxCo2IsPlausible && !needsMassTaxTable ) );
			const taxEstimateReason = isBus ? t.dqTaxBusText : isVanClass ? t.dqTaxVanText : ! taxMassIsPlausible ? ( selected.mass_source === 'technical_fallback' ? t.dqTaxTechMassText : t.dqTaxNoMassText ) : selected.powertrain === 'electric' ? t.dqTaxElectricText : needsMassTaxTable ? t.dqTaxMassTableText : number( selected.co2 ) > 500 ? t.dqTaxCo2Text : '';
			const rows = [
				{ level: 'official', title: t.dqOfficialTitle, text: t.dqOfficialText },
				{ level: officialConsumption ? 'official' : 'estimate', title: officialConsumption ? t.dqWltpTitle : t.dqConsumptionEstimateTitle, text: officialConsumption ? t.dqWltpText : t.dqConsumptionEstimateText },
				{ level: taxInputsAreReliable ? 'official' : 'estimate', title: isBus ? t.dqTaxTitle : taxInputsAreReliable ? t.dqTax2026Title : t.dqTaxEstimateTitle, text: taxInputsAreReliable ? ( isBus ? taxEstimateReason : sprintf( t.dqTaxTableText, selected.tax_measurement === 'nedc' ? 'NEDC' : 'WLTP' ) ) : taxEstimateReason },
				{ level: serviceIsVerified ? 'official' : 'estimate', title: serviceIsVerified ? t.dqServiceVerifiedTitle : t.dqServiceEstimateTitle, text: serviceIsVerified ? selected.service_source : t.dqServiceEstimateText }
			];
			if ( ! vehicleStartYear( selected ) ) rows.push( { level: 'estimate', title: t.dqUnknownYearTitle, text: t.dqUnknownYearText } );
			panel.hidden = false;
			panel.innerHTML = `<strong>${ escapeHtml( t.dataQualityTitle ) }</strong><ul>${ rows.map( row => `<li class="is-${ row.level }"><b>${ escapeHtml( row.title ) }</b><span>${ escapeHtml( row.text ) }</span></li>` ).join( '' ) }</ul>`;
		}

		function updateFieldVisibility() {
			const detailed = mode === 'detailed';
			const charging = selected && [ 'electric', 'phev' ].includes( selected.powertrain );
			root.querySelector( '.ak-detailed-fields' ).hidden = ! detailed;
			root.querySelector( '.ak-charging-fields' ).hidden = ! detailed || ! charging;
		}

		function vehicleTax( car, firstUseDate = '' ) {
			const vehicleClass = car.vehicle_class || 'M1';
			if ( [ 'M2', 'M2G', 'M3', 'M3G' ].includes( vehicleClass ) ) return 0;
			const mass = number( car.tax_mass ) || number( car.mass );
			const firstYear = vehicleStartYear( car );
			const firstUse = firstUseDate || ( firstYear ? `${ firstYear }-01-01` : '' );
			const taxTables = window.AutosiKululaskuriTax2026 || {};
			const measurement = car.tax_measurement === 'nedc' ? 'nedc' : 'wltp';
			const table = taxTables[ measurement ] || [];
			const co2 = Math.min( 400, Math.round( number( car.co2 ) ) );
			const vanClass = [ 'N1', 'N1G' ].includes( vehicleClass );
			const co2TaxThreshold = vanClass ? 2008 : mass <= 2500 ? 2001 : 2002;
			const co2TaxApplies = firstYear >= co2TaxThreshold && number( car.co2 ) > 0;
			const base = car.powertrain === 'electric'
				? ( firstUse && firstUse <= '2021-09-30' ? 106.21 : 171.18 )
				: co2TaxApplies ? ( table[ co2 ] || 106.21 ) : 106.21;
			let powerRate = 0;
			if ( car.vehicle_type === 'motorhome' ) {
				if ( car.tax_power_source === 'diesel' ) powerRate = 0.055;
				else if ( car.powertrain === 'electric' ) powerRate = 0.019;
				else if ( car.powertrain === 'phev' ) powerRate = car.tax_power_source === 'diesel' ? 0.036 : 0.0095;
			}
			else if ( vanClass ) powerRate = car.tax_power_source === 'petrol' ? 0 : 0.009;
			else if ( car.powertrain === 'electric' ) powerRate = 0.019;
			else if ( car.powertrain === 'phev' ) powerRate = car.tax_power_source === 'diesel' ? 0.036 : 0.0095;
			else if ( car.tax_power_source === 'diesel' ) powerRate = 0.055;
			const drivingPowerMass = car.vehicle_type === 'motorhome' ? Math.min( 7500, mass ) : mass;
			return base + Math.ceil( drivingPowerMass / 100 ) * 365 * powerRate;
		}

		function vehicleStartYear( car ) {
			const match = String( car.years || '' ).match( /^(\d{4})(?:[–-]\d{4})?$/ );
			const year = Number( match ? match[ 1 ] : 0 );
			return year >= 1886 && year <= new Date().getFullYear() ? year : 0;
		}

		function inspectionAnnual( car ) {
			const firstYear = vehicleStartYear( car );
			if ( ! firstYear ) return number( config.settings.inspection_price );
			const age = Math.max( 0, new Date().getFullYear() - firstYear );
			if ( age < 4 ) return 0;
			return number( config.settings.inspection_price ) / ( age >= 10 ? 1 : 2 );
		}

		function calculate() {
			if ( ! selected ) return null;
			const distance = number( fields.distance.value );
			const insurance = mode === 'detailed' ? number( fields.insurance.value ) : number( config.settings.insurance );
			const consumption = mode === 'detailed' ? number( fields.fuelConsumption.value ) : number( selected.fuel_consumption );
			const electricConsumptionBase = mode === 'detailed' ? number( fields.electricConsumption.value ) : number( selected.electric_consumption );
			const electricConsumption = electricConsumptionBase * ( 1 + number( fields.winterPenalty.value ) / 100 );
			const lossEfficiency = 1 - number( fields.chargingLoss.value ) / 100;
			const homeShare = Math.min( 100, number( fields.homeShare.value ) ) / 100;
			const avgElectricityPrice = homeShare * number( fields.homePrice.value ) + ( 1 - homeShare ) * number( fields.publicPrice.value );
			const petrolPrice = number( fields.petrolPrice.value );
			const dieselPrice = number( fields.dieselPrice.value );
			const fuelPrice = selected.powertrain === 'diesel' ? dieselPrice : petrolPrice;
			const powertrain = selected.powertrain;
			const electricShare = powertrain === 'phev' ? Math.min( 100, number( fields.electricShare.value ) ) / 100 : powertrain === 'electric' ? 1 : 0;
			const electricKm = distance * electricShare;
			const fuelKm = distance - electricKm;
			const fuel = ( fuelKm / 100 ) * consumption * fuelPrice;
			const chargedKwh = lossEfficiency > 0 ? ( electricKm / 100 ) * electricConsumption / lossEfficiency : 0;
			const electricity = chargedKwh * avgElectricityPrice;
			const tax = mode === 'detailed' ? number( fields.vehicleTax.value ) : vehicleTax( selected );
			const serviceIntervalKm = mode === 'detailed' ? number( fields.serviceIntervalKm.value ) : number( selected.service_interval_km );
			const serviceIntervalMonths = mode === 'detailed' ? number( fields.serviceIntervalMonths.value ) : number( selected.service_interval_months );
			const serviceCost = mode === 'detailed' ? number( fields.serviceCost.value ) : number( selected.service_cost );
			const serviceRuns = Math.max( distance / Math.max( 1, serviceIntervalKm ), 12 / Math.max( 1, serviceIntervalMonths ) );
			const service = serviceRuns * serviceCost;
			const inspection = inspectionAnnual( selected );
			const tyres = mode === 'detailed' ? number( fields.tyres.value ) : 390;
			const repairs = mode === 'detailed' ? number( fields.repairs.value ) : 300;
			const depreciation = mode === 'detailed' ? number( fields.depreciation.value ) : 0;
			const items = [
				{ key: 'energy', label: powertrain === 'electric' ? t.costEnergyCharging : powertrain === 'phev' ? t.costEnergyPhev : t.costEnergyFuel, value: fuel + electricity, color: '#2563eb' },
				{ key: 'insurance', label: t.costInsurance, value: insurance, color: '#14b8a6' },
				{ key: 'tax', label: t.costTax, value: tax, color: '#f59e0b' },
				{ key: 'service', label: t.costService, value: service, color: '#f97316' },
				{ key: 'inspection', label: t.costInspection, value: inspection, color: '#8b5cf6' },
				{ key: 'tyres', label: t.costTyres, value: tyres, color: '#ec4899' },
				{ key: 'repairs', label: t.costRepairs, value: repairs, color: '#64748b' },
				{ key: 'depreciation', label: t.costDepreciation, value: depreciation, color: '#334155' }
			].filter( item => item.value > 0 );
			const total = items.reduce( ( sum, item ) => sum + item.value, 0 );
			const assumptions = {
				mode,
				distance,
				insurance,
				petrolPrice,
				dieselPrice,
				homeShare,
				homePrice: number( fields.homePrice.value ),
				publicPrice: number( fields.publicPrice.value ),
				chargingLoss: number( fields.chargingLoss.value ),
				winterPenalty: number( fields.winterPenalty.value ),
				electricShare: powertrain === 'phev' ? Math.min( 100, number( fields.electricShare.value ) ) : null
			};
			return { car: selected, distance, total, monthly: total / 12, perKm: distance ? total / distance : 0, items, fuel, electricity, chargedKwh, tax, service, inspection, serviceRuns, electricShare, assumptions };
		}

		function render( result ) {
			if ( ! result ) return;
			root.querySelector( '.ak-results' ).hidden = false;
			root.querySelectorAll( '[data-result="annual"]' ).forEach( node => { node.textContent = money( result.total ); } );
			root.querySelector( '[data-result="monthly"]' ).textContent = money( result.monthly );
			root.querySelector( '[data-result="perKm"]' ).textContent = moneyExact( result.perKm );
			root.querySelector( '[data-result="breakdown"]' ).innerHTML = result.items.map( item => `<div><dt><i style="background:${ item.color }"></i>${ escapeHtml( item.label ) }</dt><dd>${ money( item.value ) }</dd></div>` ).join( '' );
			renderDonut( result );
			const charging = result.car.powertrain === 'electric' || result.car.powertrain === 'phev';
			const energyFormula = charging ? `<p><strong>${ escapeHtml( t.formulaChargingLabel ) }</strong> ${ escapeHtml( sprintf( t.formulaChargingText, money( result.electricity ), Math.round( result.chargedKwh ) ) ) }</p>` : '';
			const fuelFormula = result.fuel ? `<p><strong>${ escapeHtml( t.formulaFuelLabel ) }</strong> ${ escapeHtml( sprintf( t.formulaFuelText, money( result.fuel ), result.car.fuel_consumption ) ) }</p>` : '';
			const noAnnualTax = [ 'M2', 'M2G', 'M3', 'M3G' ].includes( result.car.vehicle_class );
			const taxExplanation = noAnnualTax ? t.formulaTaxBusText : t.formulaTaxText;
			const taxValue = noAnnualTax ? t.formulaTaxNone : money( result.tax );
			root.querySelector( '[data-result="formulas"]' ).innerHTML = `${ fuelFormula }${ energyFormula }<p><strong>${ escapeHtml( t.formulaTaxLabel ) }</strong> ${ escapeHtml( taxValue ) } — ${ escapeHtml( taxExplanation ) }</p><p><strong>${ escapeHtml( t.formulaServiceLabel ) }</strong> ${ money( result.service ) } — ${ escapeHtml( t.formulaServiceText ) }</p><p><strong>${ escapeHtml( t.formulaInspectionLabel ) }</strong> ${ money( result.inspection ) } — ${ escapeHtml( t.formulaInspectionText ) }</p>`;
		}

		function renderDonut( result ) {
			const donut = root.querySelector( '[data-chart="donut"]' );
			const legend = root.querySelector( '[data-chart="legend"]' );
			if ( ! result.items.length || ! ( result.total > 0 ) ) {
				donut.style.background = 'var(--soft)';
				donut.querySelector( 'span' ).textContent = money( 0 );
				legend.innerHTML = '';
				return;
			}
			let offset = 0;
			const stops = result.items.map( item => { const start = offset; offset += item.value / result.total * 100; return `${ item.color } ${ start }% ${ offset }%`; } );
			donut.style.position = 'relative';
			donut.style.background = `conic-gradient(${ stops.join( ',' ) })`;
			donut.querySelector( 'span' ).textContent = money( result.total );
			legend.innerHTML = result.items.map( item => `<li><i style="background:${ item.color }"></i><span>${ escapeHtml( item.label ) }</span><strong>${ Math.round( item.value / result.total * 100 ) } %</strong></li>` ).join( '' );
		}

		function addComparison() {
			const result = calculate();
			if ( ! result ) return;
			const existing = comparisons.findIndex( item => item.car.id === result.car.id );
			if ( existing !== -1 ) {
				// Re-adding the same version refreshes its figures instead of silently doing nothing.
				comparisons[ existing ] = result;
				return renderComparison();
			}
			if ( comparisons.length >= 10 ) return window.alert( t.comparisonMax );
			comparisons.push( result );
			renderComparison();
		}

		function renderComparison() {
			const section = root.querySelector( '.ak-comparison' );
			section.hidden = ! comparisons.length;
			if ( ! comparisons.length ) return;
			const max = Math.max( ...comparisons.map( item => item.total ) );
			const lowest = Math.min( ...comparisons.map( item => item.total ) );
			const categories = [
				{ key: 'energy', label: t.catEnergy },
				{ key: 'insurance', label: t.catInsurance },
				{ key: 'tax', label: t.catTax },
				{ key: 'service', label: t.catService },
				{ key: 'inspection', label: t.catInspection },
				{ key: 'tyres', label: t.catTyres },
				{ key: 'repairs', label: t.catRepairs },
				{ key: 'depreciation', label: t.catDepreciation }
			];
			const nameOf = item => `${ item.car.brand } ${ item.car.model } ${ cleanVariant( item.car ) }`;
			const chart = root.querySelector( '[data-chart="comparison"]' );
			chart.innerHTML = comparisons.map( item => {
				const name = nameOf( item );
				const isLowest = item.total === lowest;
				const delta = item.total - lowest;
				return `<div class="ak-bar-row${ isLowest ? ' is-lowest' : '' }"><span>${ escapeHtml( name ) }${ isLowest ? `<small>${ escapeHtml( t.cmpCheapestEstimate ) }</small>` : '' }</span><div role="img" aria-label="${ escapeHtml( sprintf( t.cmpBarAria, name, money( item.total ) ) ) }"><i style="width:${ max ? item.total / max * 100 : 0 }%"></i></div><strong>${ money( item.total ) }${ delta ? `<small>+ ${ money( delta ) }</small>` : '' }</strong></div>`;
			} ).join( '' );
			root.querySelector( '[data-result="comparisonHead"]' ).innerHTML = `<th scope="col">${ escapeHtml( t.cmpCar ) }</th><th scope="col">${ escapeHtml( t.cmpAnnual ) }</th><th scope="col">${ escapeHtml( t.cmpPerMonth ) }</th><th scope="col">${ escapeHtml( t.cmpPerKm ) }</th>${ categories.map( category => `<th scope="col">${ escapeHtml( category.label ) }</th>` ).join( '' ) }<th scope="col">${ escapeHtml( t.cmpDelta ) }</th><th scope="col"><span class="ak-visually-hidden">${ escapeHtml( t.cmpActions ) }</span></th>`;
			root.querySelector( '[data-result="comparisonRows"]' ).innerHTML = comparisons.map( ( item, index ) => {
				const isLowest = item.total === lowest;
				const delta = item.total - lowest;
				const amounts = Object.fromEntries( item.items.map( cost => [ cost.key, cost.value ] ) );
				const cells = categories.map( category => `<td data-label="${ escapeHtml( category.label ) }">${ money( amounts[ category.key ] || 0 ) }</td>` ).join( '' );
				return `<tr class="${ isLowest ? 'is-lowest' : '' }"><th scope="row">${ escapeHtml( nameOf( item ) ) }${ isLowest ? `<span class="ak-best-badge">${ escapeHtml( t.cmpCheapest ) }</span>` : '' }</th><td data-label="${ escapeHtml( t.cmpAnnual ) }" class="ak-total-cell">${ money( item.total ) }</td><td data-label="${ escapeHtml( t.cmpPerMonth ) }">${ money( item.monthly ) }</td><td data-label="${ escapeHtml( t.cmpPerKm ) }">${ moneyExact( item.perKm ) }</td>${ cells }<td data-label="${ escapeHtml( t.cmpDelta ) }" class="ak-delta-cell">${ delta ? `+ ${ money( delta ) }` : escapeHtml( t.cmpCheapest ) }</td><td class="ak-remove-cell"><button type="button" data-remove="${ index }" aria-label="${ escapeHtml( sprintf( t.cmpRemoveAria, nameOf( item ) ) ) }" title="${ escapeHtml( t.cmpRemoveTitle ) }">×</button></td></tr>`;
			} ).join( '' );
			const assumptions = [
				{ key: 'mode', label: t.asMode, format: value => value === 'detailed' ? t.modeDetailed : t.modeSimple },
				{ key: 'distance', label: t.asDistance, format: value => sprintf( t.unitKmPerYear, int.format( value ) ) },
				{ key: 'insurance', label: t.asInsurance, format: money },
				{ key: 'petrolPrice', label: t.asPetrolPrice, format: value => sprintf( t.unitPerLitre, euroPrecise.format( value ) ), applies: item => item.car.powertrain !== 'diesel' },
				{ key: 'dieselPrice', label: t.asDieselPrice, format: value => sprintf( t.unitPerLitre, euroPrecise.format( value ) ), applies: item => item.car.powertrain === 'diesel' },
				{ key: 'homeShare', label: t.asHomeShare, format: value => `${ value * 100 } %`, applies: item => [ 'electric', 'phev' ].includes( item.car.powertrain ) },
				{ key: 'homePrice', label: t.asHomePrice, format: value => sprintf( t.unitPerKwh, euroPrecise.format( value ) ), applies: item => [ 'electric', 'phev' ].includes( item.car.powertrain ) },
				{ key: 'publicPrice', label: t.asPublicPrice, format: value => sprintf( t.unitPerKwh, euroPrecise.format( value ) ), applies: item => [ 'electric', 'phev' ].includes( item.car.powertrain ) },
				{ key: 'chargingLoss', label: t.asChargingLoss, format: value => `${ value } %`, applies: item => [ 'electric', 'phev' ].includes( item.car.powertrain ) },
				{ key: 'winterPenalty', label: t.asWinterPenalty, format: value => `${ value } %`, applies: item => [ 'electric', 'phev' ].includes( item.car.powertrain ) },
				{ key: 'electricShare', label: t.asElectricShare, format: value => `${ value } %`, applies: item => item.car.powertrain === 'phev' }
			];
			const differences = assumptions.flatMap( assumption => {
				const relevant = comparisons.filter( item => ! assumption.applies || assumption.applies( item ) );
				if ( relevant.length < 2 || new Set( relevant.map( item => item.assumptions[ assumption.key ] ) ).size < 2 ) return [];
				return [ `${ assumption.label }: ${ relevant.map( item => `${ item.car.brand } ${ item.car.model } ${ assumption.format( item.assumptions[ assumption.key ] ) }` ).join( ' · ' ) }` ];
			} );
			const notice = root.querySelector( '[data-result="comparisonAssumptions"]' );
			notice.classList.toggle( 'has-differences', differences.length > 0 );
			notice.innerHTML = `<p><strong>${ escapeHtml( differences.length ? t.cmpAssumptionsDiffer : t.cmpAssumptionsSame ) }</strong> ${ escapeHtml( t.cmpAssumptionsNote ) }</p>${ differences.length ? `<ul>${ differences.map( difference => `<li>${ escapeHtml( difference ) }</li>` ).join( '' ) }</ul>` : '' }`;
		}

		root.querySelector( '.ak-mode-switch' ).addEventListener( 'click', event => {
			const button = event.target.closest( '[data-mode]' );
			if ( ! button ) return;
			mode = button.dataset.mode;
			root.querySelectorAll( '[data-mode]' ).forEach( item => { const active = item === button; item.classList.toggle( 'is-active', active ); item.setAttribute( 'aria-selected', active ); } );
			hideStaleResults();
			updateFieldVisibility();
			renderDataQuality();
		} );
		fields.brand.addEventListener( 'change', async () => {
			await refreshFilters();
			setModels();
		} );
		fields.vehicleType.addEventListener( 'change', async () => {
			await refreshFilters();
			setModels();
		} );
		fields.powertrain.addEventListener( 'change', async () => {
			await refreshFilters();
			setModels();
		} );
		fields.model.addEventListener( 'change', setVehicles );
		fields.vehicle.addEventListener( 'change', selectVehicle );
		fields.firstUseDate.addEventListener( 'change', () => {
			if ( selected ) fields.vehicleTax.value = Math.round( vehicleTax( selected, fields.firstUseDate.value ) );
			renderDataQuality();
		} );
		form.addEventListener( 'submit', event => { event.preventDefault(); const result = calculate(); if ( ! result ) return window.alert( t.noModel ); render( result ); } );
		root.querySelector( '[data-action="compare"]' ).addEventListener( 'click', addComparison );
		root.querySelector( '[data-action="clear-comparison"]' ).addEventListener( 'click', () => { comparisons = []; renderComparison(); } );
		root.querySelector( '[data-result="comparisonRows"]' ).addEventListener( 'click', event => { const button = event.target.closest( '[data-remove]' ); if ( ! button ) return; comparisons.splice( Number( button.dataset.remove ), 1 ); renderComparison(); } );
		initSelects();
	}

	document.querySelectorAll( '[data-component="autosi-kululaskuri"]' ).forEach( initCalculator );
}() );
