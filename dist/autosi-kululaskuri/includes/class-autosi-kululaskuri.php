<?php
/** Main plugin class. */

defined( 'ABSPATH' ) || exit;

final class Autosi_Kululaskuri {

	const OPTION_SETTINGS = 'autosi_kululaskuri_settings';
	const OPTION_CATALOG  = 'autosi_kululaskuri_catalog';
	const OPTION_CATALOG_META = 'autosi_kululaskuri_catalog_meta';
	const OPTION_CATALOG_INDEX = 'autosi_kululaskuri_catalog_index';
	const CATALOG_VERSION = '2026.10.08.2';
	const CACHE_GROUP     = 'autosi-kululaskuri';
	const CACHE_TTL       = 3600;
	const MAX_IMPORT_BYTES = 20971520; // 20 MiB upload ceiling for administrator CSV imports.
	const MAX_IMPORT_ROWS  = 250000;
	const POWERTRAINS     = array( 'petrol', 'diesel', 'hybrid', 'phev', 'electric' );

	private static $instance;

	/** Per-request memo for derived catalog indexes (brands/models/types/count). */
	private $memo = array();

	public static function instance() {
		if ( null === self::$instance ) {
			self::$instance = new self();
		}
		return self::$instance;
	}

	private function __construct() {
		add_action( 'init', array( $this, 'load_textdomain' ) );
		add_action( 'wp_enqueue_scripts', array( $this, 'register_assets' ) );
		add_shortcode( 'autosi_kululaskuri', array( $this, 'render_shortcode' ) );
		add_action( 'rest_api_init', array( $this, 'register_catalog_routes' ) );
		add_action( 'admin_menu', array( $this, 'add_admin_menu' ) );
		add_action( 'admin_init', array( $this, 'maybe_upgrade_catalog' ), 5 );
		add_action( 'admin_init', array( $this, 'register_settings' ) );
		add_action( 'admin_post_autosi_import_catalog', array( $this, 'import_catalog' ) );
		add_action( 'admin_post_autosi_reset_catalog', array( $this, 'reset_catalog' ) );
	}

	public function load_textdomain() {
		load_plugin_textdomain( 'autosi-kululaskuri', false, dirname( plugin_basename( AUTOSI_KULULASKURI_FILE ) ) . '/languages' );
	}

	public static function activate() {
		if ( false === get_option( self::OPTION_SETTINGS, false ) ) {
			add_option( self::OPTION_SETTINGS, self::default_settings() );
		}
		if ( false === get_option( self::OPTION_CATALOG, false ) ) {
			self::install_bundled_catalog();
		} elseif ( false === get_option( self::OPTION_CATALOG_META, false ) ) {
			add_option( self::OPTION_CATALOG_META, self::catalog_meta( 'custom' ) );
		}
	}

	public function maybe_upgrade_catalog() {
		$catalog = get_option( self::OPTION_CATALOG, false );
		$meta    = get_option( self::OPTION_CATALOG_META, false );
		if ( false === $catalog ) {
			self::install_bundled_catalog();
			return;
		}
		if ( ! is_array( $meta ) ) {
			// A catalogue from a pre-metadata version may be a user import. Preserve it.
			add_option( self::OPTION_CATALOG_META, self::catalog_meta( 'custom' ) );
			return;
		}
		if ( 'bundled' === ( $meta['source'] ?? '' ) && self::CATALOG_VERSION !== ( $meta['catalog_version'] ?? '' ) ) {
			self::install_bundled_catalog();
		}
	}

	public function register_assets() {
		wp_register_style( 'autosi-kululaskuri', AUTOSI_KULULASKURI_URL . 'assets/css/calculator.css', array(), AUTOSI_KULULASKURI_VERSION );
		wp_register_script( 'autosi-kululaskuri-tax', AUTOSI_KULULASKURI_URL . 'assets/js/tax-2026.js', array(), AUTOSI_KULULASKURI_VERSION, true );
		wp_register_script( 'autosi-kululaskuri', AUTOSI_KULULASKURI_URL . 'assets/js/calculator.js', array( 'autosi-kululaskuri-tax' ), AUTOSI_KULULASKURI_VERSION, true );
		wp_set_script_translations( 'autosi-kululaskuri', 'autosi-kululaskuri', AUTOSI_KULULASKURI_PATH . 'languages' );
	}

	public function render_shortcode() {
		wp_enqueue_style( 'autosi-kululaskuri' );
		wp_enqueue_script( 'autosi-kululaskuri' );

		$config = array(
			'catalogIndex' => array(
				'brands'     => $this->get_catalog_index()['brands'],
				'brandTypes' => $this->get_catalog_brand_types(),
			),
			'catalogTypes' => $this->get_catalog_types(),
			'modelsUrl'    => rest_url( 'autosi-kululaskuri/v1/catalog/models' ),
			'filtersUrl'   => rest_url( 'autosi-kululaskuri/v1/catalog/filters' ),
			'vehiclesUrl'  => rest_url( 'autosi-kululaskuri/v1/catalog/vehicles' ),
			'settings'     => $this->get_settings(),
			'locale'       => str_replace( '_', '-', determine_locale() ),
			'i18n'         => array(
				// Selection state and placeholders.
				'startPrompt'            => __( 'Valitse auto aloittaaksesi.', 'autosi-kululaskuri' ),
				'brandPlaceholder'       => __( 'Valitse merkki', 'autosi-kululaskuri' ),
				'brandPlaceholderEmpty'  => __( 'Ei merkkejä tälle tyypille', 'autosi-kululaskuri' ),
				'brandPlaceholderEmptyFuel' => __( 'Ei merkkejä tälle tyypille ja käyttövoimalle', 'autosi-kululaskuri' ),
				'modelPlaceholder'       => __( 'Valitse malli', 'autosi-kululaskuri' ),
				'versionPlaceholder'     => __( 'Valitse versio', 'autosi-kululaskuri' ),
				'loadingModels'          => __( 'Ladataan malleja...', 'autosi-kululaskuri' ),
				'loadingVersions'        => __( 'Ladataan versioita...', 'autosi-kululaskuri' ),
				'noModelsOption'         => __( 'Ei malleja tälle tyypille', 'autosi-kululaskuri' ),
				'noDataType'             => __( '(ei tietoja luettelossa)', 'autosi-kululaskuri' ),
				'noModel'                => __( 'Valitse ensin automalli.', 'autosi-kululaskuri' ),
				'noModelsForType'        => __( 'Tälle ajoneuvotyypille ei löytynyt malleja valitulla merkillä.', 'autosi-kululaskuri' ),
				'brandDroppedForFuel'    => __( 'Valitulla merkillä ei ole valittua käyttövoimaa. Valitse toinen merkki tai käyttövoima.', 'autosi-kululaskuri' ),
				'noModelsForFuel'        => __( 'Tälle merkille ei löytynyt valitun käyttövoiman malleja. Valitse toinen käyttövoima tai "Ei väliä".', 'autosi-kululaskuri' ),
				'noVersionsForFuel'      => __( 'Tälle mallille ei löytynyt valitun käyttövoiman versioita. Valitse toinen käyttövoima tai "Ei väliä".', 'autosi-kululaskuri' ),
				'vehicleTypeUnavailable' => __( 'Tälle ajoneuvotyypille ei ole tietoja tässä luettelossa.', 'autosi-kululaskuri' ),
				'catalogError'           => __( 'Autoversioiden lataus epäonnistui. Yritä uudelleen.', 'autosi-kululaskuri' ),
				'comparisonMax'          => __( 'Vertailuun voi lisätä enintään 10 autoa.', 'autosi-kululaskuri' ),
				'typeLabels'             => array(
					'petrol'   => __( 'Bensiini', 'autosi-kululaskuri' ),
					'diesel'   => __( 'Diesel', 'autosi-kululaskuri' ),
					'hybrid'   => __( 'Täyshybridi', 'autosi-kululaskuri' ),
					'phev'     => __( 'Lataushybridi', 'autosi-kululaskuri' ),
					'electric' => __( 'Sähkö', 'autosi-kululaskuri' ),
				),
				// Selected vehicle note.
				'techDataNote'           => __( 'Tekniset tiedot: Traficom 30.6.2026. %1$s %2$s %3$s %4$s (%5$s).', 'autosi-kululaskuri' ),
				'consumptionEea'         => __( 'WLTP-kulutus: EEA.', 'autosi-kululaskuri' ),
				'consumptionEstimate'    => __( 'Kulutus ja huolto: muokattavia laskenta-arvioita.', 'autosi-kululaskuri' ),
				// Data-quality panel.
				'dataQualityTitle'           => __( 'Tietojen luotettavuus', 'autosi-kululaskuri' ),
				'dqOfficialTitle'            => __( 'Virallinen avoin tieto', 'autosi-kululaskuri' ),
				'dqOfficialText'             => __( 'Merkki, malli, käyttövoima, massa ja CO₂: Traficomin avoin ajoneuvodata.', 'autosi-kululaskuri' ),
				'dqWltpTitle'                => __( 'Virallinen avoin WLTP-arvo', 'autosi-kululaskuri' ),
				'dqWltpText'                 => __( 'Kulutus tai energiankulutus: EEA:n WLTP-aineisto.', 'autosi-kululaskuri' ),
				'dqConsumptionEstimateTitle' => __( 'Laskennallinen kulutusarvo', 'autosi-kululaskuri' ),
				'dqConsumptionEstimateText'  => __( 'Kulutus on CO₂-pohjainen tai yleinen arvio. Voit muuttaa sen tarkassa laskelmassa.', 'autosi-kululaskuri' ),
				'dqTaxTitle'                 => __( 'Ajoneuvovero', 'autosi-kululaskuri' ),
				'dqTax2026Title'             => __( 'Ajoneuvovero 2026', 'autosi-kululaskuri' ),
				'dqTaxEstimateTitle'         => __( 'Ajoneuvoveron arvio', 'autosi-kululaskuri' ),
				'dqTaxTableText'             => __( 'Traficomin %s-taulukko sekä käyttövoimavero.', 'autosi-kululaskuri' ),
				'dqTaxBusText'               => __( 'Traficomin ohjeen mukaan M2/M3-linja-autoille ei lisätä tätä vuotuista ajoneuvoveroa.', 'autosi-kululaskuri' ),
				'dqTaxVanText'               => __( 'N1-vero riippuu myös dual-purpose-luokituksesta; vanhempien ja CO₂-arvottomien ajoneuvojen massataulukkoa ei ole tässä laskimessa.', 'autosi-kululaskuri' ),
				'dqTaxTechMassText'          => __( 'Tieliikenteen veromassa puuttuu; teknistä kokonaismassaa käytetään vain kulutusarviossa.', 'autosi-kululaskuri' ),
				'dqTaxNoMassText'            => __( 'Verotukseen tarvittava kokonaismassa puuttuu tai on poikkeava.', 'autosi-kululaskuri' ),
				'dqTaxElectricText'          => __( 'Tarkenna sähköauton tarkka käyttöönottopäivä. Ilman päivämäärää perusverokanta on arvio.', 'autosi-kululaskuri' ),
				'dqTaxMassTableText'         => __( 'Ajoneuvo kuuluu massa- tai puuttuvan CO₂:n verotaulukkoon, jota tämä laskin ei sisällä.', 'autosi-kululaskuri' ),
				'dqTaxCo2Text'               => __( 'CO₂-arvo on poikkeuksellisen suuri ja verotaulukko rajautuu 400 g/km:iin; tarkista ajoneuvotiedot.', 'autosi-kululaskuri' ),
				'dqServiceVerifiedTitle'     => __( 'Vahvistettu huolto-ohjelma', 'autosi-kululaskuri' ),
				'dqServiceEstimateTitle'     => __( 'Julkinen huolto-oletus', 'autosi-kululaskuri' ),
				'dqServiceEstimateText'      => __( 'Huoltokulu on Traficomin kustannuslaskurin mallia vastaava lähtöarvo. Tarkka huoltoväli ja toimenpiteet edellyttävät VIN-tietoa tai valmistajan huoltokirjaa.', 'autosi-kululaskuri' ),
				'dqUnknownYearTitle'         => __( 'Käyttöönottovuosi puuttuu', 'autosi-kululaskuri' ),
				'dqUnknownYearText'          => __( 'Tekninen katsastusvaraus lasketaan varovaisesti vuosittaisena, kun auton ikää ei voida päätellä.', 'autosi-kululaskuri' ),
				// Cost item labels.
				'costEnergyCharging' => __( 'Latausenergia', 'autosi-kululaskuri' ),
				'costEnergyPhev'     => __( 'Polttoaine ja latausenergia', 'autosi-kululaskuri' ),
				'costEnergyFuel'     => __( 'Polttoaine', 'autosi-kululaskuri' ),
				'costInsurance'      => __( 'Vakuutukset (arvio)', 'autosi-kululaskuri' ),
				'costTax'            => __( 'Ajoneuvovero', 'autosi-kululaskuri' ),
				'costService'        => __( 'Huollot', 'autosi-kululaskuri' ),
				'costInspection'     => __( 'Katsastusvaraus', 'autosi-kululaskuri' ),
				'costTyres'          => __( 'Renkaat ja vaihtotyöt', 'autosi-kululaskuri' ),
				'costRepairs'        => __( 'Korjausvaraus', 'autosi-kululaskuri' ),
				'costDepreciation'   => __( 'Arvonalenema', 'autosi-kululaskuri' ),
				// Formula explanations.
				'formulaChargingLabel'   => __( 'Latausenergia:', 'autosi-kululaskuri' ),
				'formulaChargingText'    => __( '%1$s — %2$s kWh verkosta, lataushäviö huomioitu.', 'autosi-kululaskuri' ),
				'formulaFuelLabel'       => __( 'Polttoaine:', 'autosi-kululaskuri' ),
				'formulaFuelText'        => __( '%1$s — ajomatka × %2$s l/100 km × hinta.', 'autosi-kululaskuri' ),
				'formulaTaxLabel'        => __( 'Ajoneuvovero:', 'autosi-kululaskuri' ),
				'formulaTaxNone'         => __( 'Ei lisätty', 'autosi-kululaskuri' ),
				'formulaTaxText'         => __( 'Perustuu ajoneuvoluokkaan, käyttöönottovuoteen, veromassaan, CO₂-arvoon ja käyttövoimaan. Tarkista arvio datan laatumerkinnästä.', 'autosi-kululaskuri' ),
				'formulaTaxBusText'      => __( 'Traficomin ohjeen mukaan M2/M3-linja-autoille ei lisätä vuotuista ajoneuvoveroa.', 'autosi-kululaskuri' ),
				'formulaServiceLabel'    => __( 'Huollot:', 'autosi-kululaskuri' ),
				'formulaServiceText'     => __( 'huoltoväli km tai aika, kumpi täyttyy ensin.', 'autosi-kululaskuri' ),
				'formulaInspectionLabel' => __( 'Katsastus:', 'autosi-kululaskuri' ),
				'formulaInspectionText'  => __( 'vuositasolle jaksotettu arvio.', 'autosi-kululaskuri' ),
				// Comparison chart and table.
				'cmpCar'                => __( 'Auto', 'autosi-kululaskuri' ),
				'cmpAnnual'             => __( 'Vuosikulut', 'autosi-kululaskuri' ),
				'cmpPerMonth'           => __( '€/kk', 'autosi-kululaskuri' ),
				'cmpPerKm'              => __( '€/km', 'autosi-kululaskuri' ),
				'cmpDelta'              => __( 'Ero edullisimpaan', 'autosi-kululaskuri' ),
				'cmpActions'            => __( 'Toiminnot', 'autosi-kululaskuri' ),
				'cmpBarAria'            => __( '%1$s: %2$s vuodessa', 'autosi-kululaskuri' ),
				'cmpCheapest'           => __( 'Edullisin', 'autosi-kululaskuri' ),
				'cmpCheapestEstimate'   => __( 'Edullisin arvio', 'autosi-kululaskuri' ),
				'cmpRemoveAria'         => __( 'Poista %s vertailusta', 'autosi-kululaskuri' ),
				'cmpRemoveTitle'        => __( 'Poista vertailusta', 'autosi-kululaskuri' ),
				'catEnergy'             => __( 'Energia ja polttoaine', 'autosi-kululaskuri' ),
				'catInsurance'          => __( 'Vakuutukset', 'autosi-kululaskuri' ),
				'catTax'                => __( 'Ajoneuvovero', 'autosi-kululaskuri' ),
				'catService'            => __( 'Huollot', 'autosi-kululaskuri' ),
				'catInspection'         => __( 'Katsastus', 'autosi-kululaskuri' ),
				'catTyres'              => __( 'Renkaat', 'autosi-kululaskuri' ),
				'catRepairs'            => __( 'Korjaukset', 'autosi-kululaskuri' ),
				'catDepreciation'       => __( 'Arvonalenema', 'autosi-kululaskuri' ),
				'asMode'                => __( 'Laskentatapa', 'autosi-kululaskuri' ),
				'asDistance'            => __( 'Ajokilometrit', 'autosi-kululaskuri' ),
				'asInsurance'           => __( 'Vakuutukset', 'autosi-kululaskuri' ),
				'asPetrolPrice'         => __( 'Bensiinin hinta', 'autosi-kululaskuri' ),
				'asDieselPrice'         => __( 'Dieselin hinta', 'autosi-kululaskuri' ),
				'asHomeShare'           => __( 'Kotilatauksen osuus', 'autosi-kululaskuri' ),
				'asHomePrice'           => __( 'Kotilatauksen hinta', 'autosi-kululaskuri' ),
				'asPublicPrice'         => __( 'Julkisen latauksen hinta', 'autosi-kululaskuri' ),
				'asChargingLoss'        => __( 'Lataushäviö', 'autosi-kululaskuri' ),
				'asWinterPenalty'       => __( 'Talvikulutuksen lisäys', 'autosi-kululaskuri' ),
				'asElectricShare'       => __( 'PHEV-sähköajo', 'autosi-kululaskuri' ),
				'modeSimple'            => __( 'Nopea arvio', 'autosi-kululaskuri' ),
				'modeDetailed'          => __( 'Tarkka laskelma', 'autosi-kululaskuri' ),
				'cmpAssumptionsSame'    => __( 'Yhteiset oletukset ovat samat', 'autosi-kululaskuri' ),
				'cmpAssumptionsDiffer'  => __( 'Oletukset poikkeavat autojen välillä', 'autosi-kululaskuri' ),
				'cmpAssumptionsNote'    => __( 'Kunkin auton kulutus-, vero- ja huoltoarvot tallentuvat laskentahetkellä.', 'autosi-kululaskuri' ),
				// Units.
				'unitKmPerYear'         => __( '%s km/v', 'autosi-kululaskuri' ),
				'unitPerLitre'          => __( '%s/l', 'autosi-kululaskuri' ),
				'unitPerKwh'            => __( '%s/kWh', 'autosi-kululaskuri' ),
			),
		);
		$encoded = wp_json_encode( $config );
		if ( false !== $encoded ) {
			wp_add_inline_script( 'autosi-kululaskuri', 'window.AutosiKululaskuri = ' . $encoded . ';', 'before' );
		}

		ob_start();
		include AUTOSI_KULULASKURI_PATH . 'templates/calculator.php';
		return ob_get_clean();
	}

	public function add_admin_menu() {
		add_options_page( 'Autosi Kululaskuri', 'Autosi Kululaskuri', 'manage_options', 'autosi-kululaskuri', array( $this, 'render_admin_page' ) );
	}

	public function register_catalog_routes() {
		register_rest_route(
			'autosi-kululaskuri/v1',
			'/catalog/models',
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => array( $this, 'get_catalog_models' ),
				'permission_callback' => '__return_true',
				'args'                => array(
					'brand'        => array( 'required' => true, 'sanitize_callback' => 'sanitize_text_field' ),
					'vehicle_type' => array( 'default' => '', 'sanitize_callback' => 'sanitize_key' ),
					'powertrain'   => array( 'default' => '', 'sanitize_callback' => 'sanitize_key' ),
				),
			)
		);
		register_rest_route(
			'autosi-kululaskuri/v1',
			'/catalog/filters',
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => array( $this, 'get_catalog_filters' ),
				'permission_callback' => '__return_true',
				'args'                => array(
					'vehicle_type' => array( 'default' => '', 'sanitize_callback' => 'sanitize_key' ),
					'powertrain'   => array( 'default' => '', 'sanitize_callback' => 'sanitize_key' ),
				),
			)
		);
		register_rest_route(
			'autosi-kululaskuri/v1',
			'/catalog/vehicles',
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => array( $this, 'get_catalog_vehicles' ),
				'permission_callback' => '__return_true',
				'args'                => array(
					'brand'        => array( 'required' => true, 'sanitize_callback' => 'sanitize_text_field' ),
					'model'        => array( 'required' => true, 'sanitize_callback' => 'sanitize_text_field' ),
					'vehicle_type' => array( 'default' => '', 'sanitize_callback' => 'sanitize_key' ),
					'powertrain'   => array( 'default' => '', 'sanitize_callback' => 'sanitize_key' ),
				),
			)
		);
	}

	public function get_catalog_models( $request ) {
		$brand = $request->get_param( 'brand' );
		$vehicle_type = $request->get_param( 'vehicle_type' );
		$powertrain   = $request->get_param( 'powertrain' );
		if ( ! in_array( $powertrain, self::POWERTRAINS, true ) ) {
			$powertrain = '';
		}
		$meta = $this->get_catalog_meta();
		$cache_key = $this->cache_key( $meta, 'models', $brand, $vehicle_type, $powertrain );
		$models = $this->cache_get( $cache_key );
		if ( false === $models ) {
			$model_set = array();
			foreach ( $this->get_catalog_index()['models'] as $item ) {
				if ( $item['brand'] !== $brand || ! self::vehicle_type_matches( $item, $vehicle_type ) ) {
					continue;
				}
				// Rows from a catalogue without powertrain data are never filtered away.
				if ( '' !== $powertrain && ! empty( $item['powertrains'] ) && ! in_array( $powertrain, $item['powertrains'], true ) ) {
					continue;
				}
				$model_set[ $item['model'] ] = true;
			}
			$models = array_keys( $model_set );
			sort( $models, SORT_NATURAL | SORT_FLAG_CASE );
			$this->cache_set( $cache_key, $models );
		}
		return rest_ensure_response( $models );
	}

	/**
	 * The options still valid for the current picker selection: which makes still have a model
	 * for the chosen vehicle type and fuel, and which fuels and vehicle types have data. Every
	 * list is narrowed by the fields that precede it in the form only, so choosing a value can
	 * never reset that same field. A catalogue without powertrain data returns the unfiltered
	 * lists, so nothing disappears when the data is unavailable.
	 */
	public function get_catalog_filters( $request ) {
		$vehicle_type = $request->get_param( 'vehicle_type' );
		$powertrain   = $request->get_param( 'powertrain' );
		if ( ! in_array( $powertrain, self::POWERTRAINS, true ) ) {
			$powertrain = '';
		}
		$meta = $this->get_catalog_meta();
		$cache_key = $this->cache_key( $meta, 'filters', $vehicle_type, $powertrain );
		$filters = $this->cache_get( $cache_key );
		if ( false === $filters ) {
			$filters = $this->build_catalog_filters( $vehicle_type, $powertrain );
			$this->cache_set( $cache_key, $filters );
		}
		return rest_ensure_response( $filters );
	}

	private function build_catalog_filters( $vehicle_type, $powertrain ) {
		$availability = $this->get_catalog_availability();
		if ( ! $availability ) {
			return array(
				'brands'       => $this->get_catalog_index()['brands'],
				'powertrains'  => array_values( self::POWERTRAINS ),
				'vehicleTypes' => $this->get_catalog_types(),
			);
		}

		$brands = array();
		foreach ( $availability as $name => $type_codes ) {
			if ( '' !== $vehicle_type && ! isset( $type_codes[ $vehicle_type ] ) ) {
				continue;
			}
			if ( '' !== $powertrain ) {
				$codes = array();
				foreach ( ( '' !== $vehicle_type ? array( $vehicle_type => $type_codes[ $vehicle_type ] ) : $type_codes ) as $fuel_codes ) {
					$codes = array_merge( $codes, $fuel_codes );
				}
				if ( ! in_array( $powertrain, $codes, true ) ) {
					continue;
				}
			}
			$brands[] = $name;
		}
		sort( $brands, SORT_NATURAL | SORT_FLAG_CASE );

		// Fuels are narrowed by the vehicle type only: the fuel field precedes the make in the
		// form, so a make choice must never drop the fuel the user just picked.
		$fuel_sets = array();
		foreach ( $availability as $type_codes ) {
			foreach ( $type_codes as $type => $fuel_codes ) {
				if ( '' === $vehicle_type || $type === $vehicle_type ) {
					$fuel_sets[] = $fuel_codes;
				}
			}
		}
		$powertrains = array();
		foreach ( $fuel_sets as $fuel_codes ) {
			$powertrains = array_merge( $powertrains, $fuel_codes );
		}
		$powertrains = array_values( array_intersect( self::POWERTRAINS, array_unique( $powertrains ) ) );

		$vehicle_types = array();
		foreach ( $availability as $type_codes ) {
			foreach ( $type_codes as $type => $fuel_codes ) {
				if ( '' === $powertrain || in_array( $powertrain, $fuel_codes, true ) ) {
					$vehicle_types[ $type ] = true;
				}
			}
		}
		$vehicle_types = array_keys( $vehicle_types );
		sort( $vehicle_types, SORT_NATURAL | SORT_FLAG_CASE );

		return array(
			'brands'       => $brands,
			'powertrains'  => $powertrains,
			'vehicleTypes' => $vehicle_types,
		);
	}

	public function get_catalog_vehicles( $request ) {
		$brand = $request->get_param( 'brand' );
		$model = $request->get_param( 'model' );
		$vehicle_type = $request->get_param( 'vehicle_type' );
		$powertrain   = $request->get_param( 'powertrain' );
		if ( ! in_array( $powertrain, self::POWERTRAINS, true ) ) {
			$powertrain = '';
		}
		$meta = $this->get_catalog_meta();
		$cache_key = $this->cache_key( $meta, 'vehicles', $brand, $model, $vehicle_type, $powertrain );
		$vehicles = $this->cache_get( $cache_key );
		if ( false === $vehicles ) {
			if ( 'bundled' === $meta['source'] && ( '' === $vehicle_type || in_array( $vehicle_type, self::verified_catalog()['vehicleTypes'] ?? array(), true ) ) ) {
				$shard = substr( hash( 'sha256', $brand . "\0" . $model ), 0, 2 );
				$path = AUTOSI_KULULASKURI_PATH . 'data/traficom-catalog-2026/' . $shard . '.json.gz';
				$compressed = is_readable( $path ) ? file_get_contents( $path ) : false;
				$decoded = false !== $compressed && function_exists( 'gzdecode' ) ? gzdecode( $compressed ) : false;
				$shard_vehicles = false !== $decoded ? json_decode( $decoded, true ) : false;
				if ( ! is_array( $shard_vehicles ) ) {
					return new WP_Error( 'autosi_catalog_unavailable', __( 'Ajoneuvoversioiden lataus epäonnistui.', 'autosi-kululaskuri' ), array( 'status' => 500 ) );
				}
				$vehicles = array_values(
					array_filter(
						$shard_vehicles,
					static function ( $vehicle ) use ( $brand, $model, $vehicle_type, $powertrain ) {
						return $vehicle['brand'] === $brand && $vehicle['model'] === $model && self::vehicle_type_matches( $vehicle, $vehicle_type ) && self::powertrain_matches( $vehicle, $powertrain );
					}
				)
				);
			} elseif ( 'bundled' !== $meta['source'] ) {
				$vehicles = array_values(
					array_filter(
						$this->get_catalog(),
						static function ( $vehicle ) use ( $brand, $model, $vehicle_type, $powertrain ) {
							return $vehicle['brand'] === $brand && $vehicle['model'] === $model && self::vehicle_type_matches( $vehicle, $vehicle_type ) && self::powertrain_matches( $vehicle, $powertrain );
						}
					)
				);
			} else {
				$vehicles = array();
			}
			$this->cache_set( $cache_key, $vehicles );
		}
		return rest_ensure_response( $vehicles );
	}

	private static function vehicle_type_matches( $vehicle, $vehicle_type ) {
		return '' === $vehicle_type || ( $vehicle['vehicle_type'] ?? 'passenger' ) === $vehicle_type;
	}

	private static function powertrain_matches( $vehicle, $powertrain ) {
		return '' === $powertrain || ( $vehicle['powertrain'] ?? '' ) === $powertrain;
	}

	/**
	 * Build a cache key tied to the current catalog source and revision, so an import
	 * or bundled-catalog upgrade naturally invalidates older entries.
	 */
	private function cache_key( $meta, $kind, ...$parts ) {
		return 'autosi_kl_' . md5( $meta['source'] . "\0" . $meta['updated_at'] . "\0" . $kind . "\0" . implode( "\0", $parts ) );
	}

	/**
	 * Read a cached REST payload. The object cache is the fast path; on hosts without a
	 * persistent object cache a transient keeps the result across requests instead of
	 * decompressing the catalog shard on every call.
	 */
	private function cache_get( $key ) {
		$found = false;
		$value = wp_cache_get( $key, self::CACHE_GROUP, false, $found );
		if ( $found ) {
			return $value;
		}
		return wp_using_ext_object_cache() ? false : get_transient( $key );
	}

	private function cache_set( $key, $value ) {
		wp_cache_set( $key, $value, self::CACHE_GROUP, self::CACHE_TTL );
		if ( ! wp_using_ext_object_cache() ) {
			set_transient( $key, $value, self::CACHE_TTL );
		}
	}

	private function memo_get( $key ) {
		return array_key_exists( $key, $this->memo ) ? $this->memo[ $key ] : null;
	}

	private function memo_set( $key, $value ) {
		$this->memo[ $key ] = $value;
		return $value;
	}

	public function register_settings() {
		register_setting( 'autosi_kululaskuri', self::OPTION_SETTINGS, array( $this, 'sanitize_settings' ) );
	}

	public function sanitize_settings( $input ) {
		$defaults = self::default_settings();
		$clean    = array();
		foreach ( $defaults as $key => $value ) {
			$clean[ $key ] = isset( $input[ $key ] ) ? max( 0, (float) str_replace( ',', '.', $input[ $key ] ) ) : $value;
		}
		return $clean;
	}

	public function render_admin_page() {
		if ( ! current_user_can( 'manage_options' ) ) {
			return;
		}
		$settings = $this->get_settings();
		$catalog_count = $this->get_catalog_count();
		$meta     = $this->get_catalog_meta();
		$message  = isset( $_GET['autosi_message'] ) ? sanitize_key( wp_unslash( $_GET['autosi_message'] ) ) : '';
		?>
		<div class="wrap">
			<h1>Autosi Kululaskuri</h1>
			<?php if ( 'imported' === $message || 'reset' === $message ) : ?>
				<div class="notice notice-success is-dismissible"><p><?php esc_html_e( 'Ajoneuvoluettelo tallennettiin.', 'autosi-kululaskuri' ); ?></p></div>
			<?php elseif ( 'invalid-csv' === $message || 'missing-file' === $message ) : ?>
				<div class="notice notice-error"><p><?php esc_html_e( 'CSV-tiedostoa ei voitu tuoda. Tarkista pakolliset sarakkeet ja tiedoston muoto.', 'autosi-kululaskuri' ); ?></p></div>
			<?php elseif ( 'too-large' === $message ) : ?>
				<div class="notice notice-error"><p><?php esc_html_e( 'CSV-tiedosto on liian suuri tuotavaksi. Enimmäiskoko on 20 MiB ja enintään 250 000 riviä.', 'autosi-kululaskuri' ); ?></p></div>
			<?php endif; ?>
			<p><?php esc_html_e( 'Oletushinnat ovat arvioita. Päivitä ne säännöllisesti ja kerro sivustolla laskelman olevan suuntaa-antava.', 'autosi-kululaskuri' ); ?></p>
			<form method="post" action="options.php">
				<?php settings_fields( 'autosi_kululaskuri' ); ?>
				<table class="form-table" role="presentation">
					<tr><th scope="row"><label for="petrol_price"><?php esc_html_e( 'Bensiini, €/l', 'autosi-kululaskuri' ); ?></label></th><td><input id="petrol_price" name="<?php echo esc_attr( self::OPTION_SETTINGS ); ?>[petrol_price]" value="<?php echo esc_attr( $settings['petrol_price'] ); ?>" type="number" min="0" step="0.001"></td></tr>
					<tr><th scope="row"><label for="diesel_price"><?php esc_html_e( 'Diesel, €/l', 'autosi-kululaskuri' ); ?></label></th><td><input id="diesel_price" name="<?php echo esc_attr( self::OPTION_SETTINGS ); ?>[diesel_price]" value="<?php echo esc_attr( $settings['diesel_price'] ); ?>" type="number" min="0" step="0.001"></td></tr>
					<tr><th scope="row"><label for="home_electricity"><?php esc_html_e( 'Kotilataus, €/kWh', 'autosi-kululaskuri' ); ?></label></th><td><input id="home_electricity" name="<?php echo esc_attr( self::OPTION_SETTINGS ); ?>[home_electricity]" value="<?php echo esc_attr( $settings['home_electricity'] ); ?>" type="number" min="0" step="0.001"></td></tr>
					<tr><th scope="row"><label for="public_electricity"><?php esc_html_e( 'Julkinen lataus, €/kWh', 'autosi-kululaskuri' ); ?></label></th><td><input id="public_electricity" name="<?php echo esc_attr( self::OPTION_SETTINGS ); ?>[public_electricity]" value="<?php echo esc_attr( $settings['public_electricity'] ); ?>" type="number" min="0" step="0.001"></td></tr>
					<tr><th scope="row"><label for="insurance"><?php esc_html_e( 'Vakuutusarvio, €/vuosi', 'autosi-kululaskuri' ); ?></label></th><td><input id="insurance" name="<?php echo esc_attr( self::OPTION_SETTINGS ); ?>[insurance]" value="<?php echo esc_attr( $settings['insurance'] ); ?>" type="number" min="0" step="1"></td></tr>
					<tr><th scope="row"><label for="inspection_price"><?php esc_html_e( 'Katsastus, €', 'autosi-kululaskuri' ); ?></label></th><td><input id="inspection_price" name="<?php echo esc_attr( self::OPTION_SETTINGS ); ?>[inspection_price]" value="<?php echo esc_attr( $settings['inspection_price'] ); ?>" type="number" min="0" step="1"></td></tr>
				</table>
				<?php submit_button( __( 'Tallenna oletushinnat', 'autosi-kululaskuri' ) ); ?>
			</form>

			<hr>
			<h2>
				<?php
				printf(
					/* translators: %s: number of catalogue versions. */
					esc_html__( 'Ajoneuvoluettelo (%s versiota)', 'autosi-kululaskuri' ),
					esc_html( $catalog_count )
				);
				?>
			</h2>
			<p>
				<?php esc_html_e( 'Lähde:', 'autosi-kululaskuri' ); ?>
				<strong><?php echo esc_html( 'bundled' === $meta['source'] ? __( 'sisäänrakennettu Traficom-luettelo', 'autosi-kululaskuri' ) : __( 'ylläpitäjän tuoma CSV', 'autosi-kululaskuri' ) ); ?></strong>.
				<?php esc_html_e( 'Versio:', 'autosi-kululaskuri' ); ?>
				<?php echo esc_html( $meta['catalog_version'] ? $meta['catalog_version'] : __( 'oma tuonti', 'autosi-kululaskuri' ) ); ?>.
			</p>
			<p>
				<?php esc_html_e( 'Tuo CSV UTF-8 -muodossa. Pakolliset sarakkeet:', 'autosi-kululaskuri' ); ?>
				<code>id,brand,model,powertrain</code>.
				<?php esc_html_e( 'Ajoneuvotyyppi on vapaaehtoinen sarake', 'autosi-kululaskuri' ); ?>
				<code>vehicle_type</code>:
				<code>passenger,light_truck,minibus,van,motorhome,bus,special,pickup</code>.
				<?php esc_html_e( 'Ajoneuvoluokan voi antaa sarakkeessa', 'autosi-kululaskuri' ); ?>
				<code>vehicle_class</code>;
				<?php esc_html_e( 'massakentistä', 'autosi-kululaskuri' ); ?>
				<code>tax_mass</code>
				<?php esc_html_e( 'on tieliikenteessä sallittu veromassa, ei tekninen enimmäismassa.', 'autosi-kululaskuri' ); ?>
			</p>
			<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>" enctype="multipart/form-data">
				<?php wp_nonce_field( 'autosi_import_catalog' ); ?>
				<input type="hidden" name="action" value="autosi_import_catalog">
				<input name="catalog_csv" type="file" accept=".csv,text/csv" required>
				<?php submit_button( __( 'Tuo ja korvaa luettelo', 'autosi-kululaskuri' ), 'secondary', 'submit', false ); ?>
			</form>
			<?php if ( 'bundled' !== $meta['source'] ) : ?>
				<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>" style="margin-top:12px">
					<?php wp_nonce_field( 'autosi_reset_catalog' ); ?>
					<input type="hidden" name="action" value="autosi_reset_catalog">
					<?php submit_button( __( 'Palauta sisäänrakennettu Traficom-luettelo', 'autosi-kululaskuri' ), 'delete', 'submit', false ); ?>
				</form>
			<?php endif; ?>
		</div>
		<?php
	}

	public function import_catalog() {
		if ( ! current_user_can( 'manage_options' ) || ! check_admin_referer( 'autosi_import_catalog' ) ) {
			wp_die( esc_html__( 'Ei oikeutta.', 'autosi-kululaskuri' ) );
		}
		$upload = isset( $_FILES['catalog_csv'] ) ? $_FILES['catalog_csv'] : array(); // phpcs:ignore WordPress.Security.ValidatedSanitizedInput
		$error  = isset( $upload['error'] ) ? (int) $upload['error'] : UPLOAD_ERR_NO_FILE;
		if ( empty( $upload['tmp_name'] ) || UPLOAD_ERR_OK !== $error ) {
			wp_safe_redirect( add_query_arg( 'autosi_message', 'missing-file', admin_url( 'options-general.php?page=autosi-kululaskuri' ) ) );
			exit;
		}
		if ( ! empty( $upload['size'] ) && (int) $upload['size'] > self::MAX_IMPORT_BYTES ) {
			wp_safe_redirect( add_query_arg( 'autosi_message', 'too-large', admin_url( 'options-general.php?page=autosi-kululaskuri' ) ) );
			exit;
		}
		$handle = fopen( $upload['tmp_name'], 'r' ); // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_operations_fopen
		$header = $handle ? fgetcsv( $handle ) : false;
		$items  = array();
		$truncated = false;
		if ( $header ) {
			$header = array_map( 'sanitize_key', $header );
			while ( ( $row = fgetcsv( $handle ) ) !== false ) {
				if ( count( $row ) !== count( $header ) ) {
					continue;
				}
				if ( count( $items ) >= self::MAX_IMPORT_ROWS ) {
					$truncated = true;
					break;
				}
				$item = array_combine( $header, $row );
				if ( empty( $item['id'] ) || empty( $item['brand'] ) || empty( $item['model'] ) || empty( $item['powertrain'] ) ) {
					continue;
				}
				$clean = $this->sanitize_catalog_item( $item );
				if ( $clean ) {
					$items[] = $clean;
				}
			}
		}
		if ( $handle ) {
			fclose( $handle ); // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_operations_fclose
		}
		if ( $truncated ) {
			$message = 'too-large';
		} elseif ( $items ) {
			update_option( self::OPTION_CATALOG, $items, false );
			update_option( self::OPTION_CATALOG_INDEX, self::build_catalog_index( $items ), false );
			update_option( self::OPTION_CATALOG_META, self::catalog_meta( 'custom' ) );
			$message = 'imported';
		} else {
			$message = 'invalid-csv';
		}
		wp_safe_redirect( add_query_arg( 'autosi_message', $message, admin_url( 'options-general.php?page=autosi-kululaskuri' ) ) );
		exit;
	}

	public function reset_catalog() {
		if ( ! current_user_can( 'manage_options' ) || ! check_admin_referer( 'autosi_reset_catalog' ) ) {
			wp_die( esc_html__( 'Ei oikeutta.', 'autosi-kululaskuri' ) );
		}
		self::install_bundled_catalog();
		wp_safe_redirect( add_query_arg( 'autosi_message', 'reset', admin_url( 'options-general.php?page=autosi-kululaskuri' ) ) );
		exit;
	}

	private function sanitize_catalog_item( $item ) {
		$text_fields = array( 'id', 'brand', 'model', 'variant', 'years', 'powertrain', 'vehicle_type', 'vehicle_class', 'body_type', 'mass_source', 'tax_measurement', 'tax_power_source', 'source', 'consumption_source', 'service_source', 'data_status', 'type_approval', 'variant_code', 'version_code', 'eea_type_approval' );
		$number_fields = array( 'fuel_consumption', 'electric_consumption', 'co2', 'mass', 'tax_mass', 'road_mass', 'technical_mass', 'curb_mass', 'seats', 'service_cost', 'service_interval_km', 'service_interval_months', 'source_rank', 'registered_count', 'eea_year' );
		$defaults = self::catalog_defaults();
		$clean = array();
		foreach ( $text_fields as $field ) {
			$clean[ $field ] = isset( $item[ $field ] ) && '' !== trim( (string) $item[ $field ] ) ? sanitize_text_field( $item[ $field ] ) : $defaults[ $field ];
		}
		foreach ( $number_fields as $field ) {
			$clean[ $field ] = isset( $item[ $field ] ) && '' !== trim( (string) $item[ $field ] ) ? max( 0, (float) str_replace( ',', '.', $item[ $field ] ) ) : $defaults[ $field ];
		}
		$clean['powertrain'] = strtolower( $clean['powertrain'] );
		if ( ! in_array( $clean['powertrain'], self::POWERTRAINS, true ) ) {
			return false;
		}
		if ( ! in_array( $clean['vehicle_type'], array( 'passenger', 'light_truck', 'minibus', 'van', 'motorhome', 'bus', 'special', 'pickup' ), true ) ) {
			return false;
		}
		if ( ! in_array( $clean['vehicle_class'], array( '', 'M1', 'M1G', 'N1', 'N1G', 'M2', 'M2G', 'M3', 'M3G' ), true ) ) {
			return false;
		}
		$clean['id'] = sanitize_key( $clean['id'] );
		$clean['variant'] = $clean['variant'] ?: $clean['model'];
		return $clean;
	}

	private function get_settings() {
		return wp_parse_args( get_option( self::OPTION_SETTINGS, array() ), self::default_settings() );
	}

	private function get_catalog() {
		$meta = $this->get_catalog_meta();
		if ( 'bundled' === $meta['source'] ) {
			return array();
		}
		$catalog = get_option( self::OPTION_CATALOG, array() );
		return is_array( $catalog ) ? $catalog : array();
	}

	private function get_catalog_index() {
		if ( null !== ( $cached = $this->memo_get( 'index' ) ) ) {
			return $cached;
		}
		$meta = $this->get_catalog_meta();
		if ( 'bundled' === $meta['source'] ) {
			return $this->memo_set( 'index', self::verified_catalog() );
		}
		// Administrator imports store a precomputed index; rebuild lazily for legacy imports.
		$index = get_option( self::OPTION_CATALOG_INDEX, false );
		if ( ! is_array( $index ) || ! isset( $index['models'], $index['brands'], $index['availability'] ) ) {
			$index = self::build_catalog_index( $this->get_catalog() );
			update_option( self::OPTION_CATALOG_INDEX, $index, false );
		}
		return $this->memo_set( 'index', $index );
	}

	private function get_catalog_types() {
		if ( null !== ( $cached = $this->memo_get( 'types' ) ) ) {
			return $cached;
		}
		$index = $this->get_catalog_index();
		return $this->memo_set( 'types', $index['vehicleTypes'] ?? array( 'passenger' ) );
	}

	private function get_catalog_brand_types() {
		if ( null !== ( $cached = $this->memo_get( 'brand_types' ) ) ) {
			return $cached;
		}
		$index = $this->get_catalog_index();
		if ( isset( $index['brandTypes'] ) ) {
			return $this->memo_set( 'brand_types', $index['brandTypes'] );
		}
		$map = array();
		foreach ( $index['models'] as $entry ) {
			$map[ $entry['brand'] ][ $entry['vehicle_type'] ?? 'passenger' ] = true;
		}
		return $this->memo_set( 'brand_types', array_map( 'array_keys', $map ) );
	}

	/**
	 * {make: {vehicle_type: [powertrain codes]}} used to narrow the picker cascade.
	 * Catalogues written before this map existed fall back to the per-row powertrains.
	 */
	private function get_catalog_availability() {
		if ( null !== ( $cached = $this->memo_get( 'availability' ) ) ) {
			return $cached;
		}
		$index = $this->get_catalog_index();
		if ( ! empty( $index['availability'] ) ) {
			return $this->memo_set( 'availability', $index['availability'] );
		}
		$codes_by_type = array();
		foreach ( $index['models'] as $entry ) {
			$type = $entry['vehicle_type'] ?? 'passenger';
			foreach ( ( $entry['powertrains'] ?? array() ) as $code ) {
				if ( in_array( $code, self::POWERTRAINS, true ) ) {
					$codes_by_type[ $entry['brand'] ][ $type ][ $code ] = true;
				}
			}
		}
		$availability = array();
		foreach ( $codes_by_type as $name => $type_codes ) {
			foreach ( $type_codes as $type => $codes ) {
				$availability[ $name ][ $type ] = array_values( array_intersect( self::POWERTRAINS, array_keys( $codes ) ) );
			}
		}
		return $this->memo_set( 'availability', $availability );
	}

	private function get_catalog_count() {
		if ( null !== ( $cached = $this->memo_get( 'count' ) ) ) {
			return $cached;
		}
		$index = $this->get_catalog_index();
		return $this->memo_set( 'count', (int) ( $index['count'] ?? 0 ) );
	}

	private function get_catalog_meta() {
		$meta = get_option( self::OPTION_CATALOG_META, array() );
		return wp_parse_args( is_array( $meta ) ? $meta : array(), self::catalog_meta( 'custom' ) );
	}

	private static function install_bundled_catalog() {
		delete_option( self::OPTION_CATALOG );
		delete_option( self::OPTION_CATALOG_INDEX );
		update_option( self::OPTION_CATALOG_META, self::catalog_meta( 'bundled' ) );
	}

	/**
	 * Precompute the selectable catalog index (brands, models, types) once at import time,
	 * so page renders and REST calls never scan the full administrator catalog.
	 * Mirrors the shape of the bundled index file.
	 */
	private static function build_catalog_index( $items ) {
		$brands = array();
		$models = array();
		$types  = array();
		$brand_types  = array();
		$powertrains  = array();
		$availability = array();
		foreach ( $items as $vehicle ) {
			$brand = $vehicle['brand'];
			$model = $vehicle['model'];
			$type  = $vehicle['vehicle_type'] ?? 'passenger';
			$code  = $vehicle['powertrain'] ?? '';
			$brands[ $brand ] = true;
			$types[ $type ]   = true;
			$brand_types[ $brand ][ $type ] = true;
			$models[ $brand . "\0" . $model . "\0" . $type ] = array(
				'brand'        => $brand,
				'model'        => $model,
				'vehicle_type' => $type,
				'powertrains'  => array(),
			);
			if ( '' !== $code && in_array( $code, self::POWERTRAINS, true ) ) {
				$powertrains[ $brand . "\0" . $model . "\0" . $type ][ $code ] = true;
				$availability[ $brand ][ $type ][ $code ] = true;
			}
		}
		foreach ( $models as $key => $entry ) {
			$models[ $key ]['powertrains'] = array_values( array_intersect( self::POWERTRAINS, array_keys( $powertrains[ $key ] ?? array() ) ) );
		}
		foreach ( $availability as $name => $type_codes ) {
			foreach ( $type_codes as $type => $codes ) {
				$availability[ $name ][ $type ] = array_values( array_intersect( self::POWERTRAINS, array_keys( $codes ) ) );
			}
		}
		$brands = array_keys( $brands );
		sort( $brands, SORT_NATURAL | SORT_FLAG_CASE );
		$types = array_keys( $types );
		sort( $types, SORT_NATURAL | SORT_FLAG_CASE );
		$models = array_values( $models );
		usort(
			$models,
			static function ( $left, $right ) {
				$brand_order = strnatcasecmp( $left['brand'], $right['brand'] );
				return 0 === $brand_order ? strnatcasecmp( $left['model'], $right['model'] ) : $brand_order;
			}
		);
		return array(
			'count'        => count( $items ),
			'brands'       => $brands,
			'models'       => $models,
			'vehicleTypes' => $types,
			'brandTypes'   => array_map( 'array_keys', $brand_types ),
			'availability' => $availability,
		);
	}

	private static function catalog_meta( $source ) {
		return array(
			'source'          => $source,
			'catalog_version' => 'bundled' === $source ? self::CATALOG_VERSION : '',
			'updated_at'      => gmdate( 'c' ),
		);
	}

	private static function catalog_defaults() {
		return array(
			'id'                      => '',
			'brand'                   => '',
			'model'                   => '',
			'variant'                 => '',
			'years'                   => '',
			'powertrain'              => '',
			'vehicle_type'            => 'passenger',
			'vehicle_class'           => '',
			'body_type'               => '',
			'mass_source'             => 'administrator',
			'tax_measurement'         => 'wltp',
			'tax_power_source'        => 'petrol',
			'source'                  => 'Administrator CSV import',
			'consumption_source'      => 'Administrator-provided value',
			'service_source'          => 'Public benchmark: Traficom calculator methodology; verify against VIN/manufacturer plan',
			'data_status'             => 'administrator-imported',
			'type_approval'           => '',
			'variant_code'            => '',
			'version_code'            => '',
			'eea_type_approval'       => '',
			'fuel_consumption'        => 0,
			'electric_consumption'    => 0,
			'co2'                     => 0,
			'mass'                    => 0,
			'tax_mass'                => 0,
			'road_mass'               => 0,
			'technical_mass'          => 0,
			'curb_mass'               => 0,
			'seats'                   => 0,
			'service_cost'            => 360,
			'service_interval_km'     => 15000,
			'service_interval_months' => 12,
			'source_rank'             => 0,
			'registered_count'        => 0,
			'eea_year'                => 0,
		);
	}

	private static function verified_catalog() {
		static $catalog_index;
		if ( null === $catalog_index ) {
			$catalog_index = require AUTOSI_KULULASKURI_PATH . 'data/traficom-catalog-2026.php';
		}
		return $catalog_index;
	}

	private static function default_settings() {
		return array(
			'petrol_price'       => 2.08,
			'diesel_price'       => 2.25,
			'home_electricity'   => 0.195,
			'public_electricity' => 0.45,
			'insurance'          => 680,
			'inspection_price'   => 65,
		);
	}

}
