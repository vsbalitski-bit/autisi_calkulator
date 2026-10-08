<?php
/**
 * Calculator template. All user-facing strings are translatable.
 *
 * @package Autosi_Kululaskuri
 */

defined( 'ABSPATH' ) || exit;
?>
<section class="ak-calculator" data-component="autosi-kululaskuri">
	<header class="ak-header">
		<p class="ak-eyebrow"><?php esc_html_e( 'AUTOSI KULULASKURI', 'autosi-kululaskuri' ); ?></p>
		<h2><?php esc_html_e( 'Auton vuosikulut selkeästi', 'autosi-kululaskuri' ); ?></h2>
		<p><?php esc_html_e( 'Laske auton käyttö- ja kokonaiskulut. Tulos on arvio — tarkista aina omat sopimus- ja ajoneuvotietosi.', 'autosi-kululaskuri' ); ?></p>
	</header>

	<div class="ak-mode-switch" role="tablist" aria-label="<?php esc_attr_e( 'Laskentatapa', 'autosi-kululaskuri' ); ?>">
		<button class="is-active" type="button" role="tab" aria-selected="true" data-mode="simple"><?php esc_html_e( 'Nopea arvio', 'autosi-kululaskuri' ); ?></button>
		<button type="button" role="tab" aria-selected="false" data-mode="detailed"><?php esc_html_e( 'Tarkka laskelma', 'autosi-kululaskuri' ); ?></button>
	</div>

	<form class="ak-form" novalidate>
		<div class="ak-fields ak-core-fields">
			<label><span><?php esc_html_e( 'Auton tyyppi', 'autosi-kululaskuri' ); ?></span><select name="vehicleType"><option value=""><?php esc_html_e( 'Ei väliä', 'autosi-kululaskuri' ); ?></option><option value="passenger"><?php esc_html_e( 'Henkilöauto', 'autosi-kululaskuri' ); ?></option><option value="light_truck"><?php esc_html_e( 'Kevyt kuorma-auto', 'autosi-kululaskuri' ); ?></option><option value="minibus"><?php esc_html_e( 'Minibussi', 'autosi-kululaskuri' ); ?></option><option value="van"><?php esc_html_e( 'Pakettiauto', 'autosi-kululaskuri' ); ?></option><option value="motorhome"><?php esc_html_e( 'Matkailuauto', 'autosi-kululaskuri' ); ?></option><option value="bus"><?php esc_html_e( 'Linja-auto', 'autosi-kululaskuri' ); ?></option><option value="special"><?php esc_html_e( 'Erikoisajoneuvo', 'autosi-kululaskuri' ); ?></option><option value="pickup"><?php esc_html_e( 'Avolava-auto', 'autosi-kululaskuri' ); ?></option></select></label>
			<label><span><?php esc_html_e( 'Käyttövoima', 'autosi-kululaskuri' ); ?></span><select name="powertrain"><option value=""><?php esc_html_e( 'Ei väliä', 'autosi-kululaskuri' ); ?></option><option value="petrol"><?php esc_html_e( 'Bensiini', 'autosi-kululaskuri' ); ?></option><option value="diesel"><?php esc_html_e( 'Diesel', 'autosi-kululaskuri' ); ?></option><option value="hybrid"><?php esc_html_e( 'Täyshybridi', 'autosi-kululaskuri' ); ?></option><option value="phev"><?php esc_html_e( 'Lataushybridi', 'autosi-kululaskuri' ); ?></option><option value="electric"><?php esc_html_e( 'Sähkö', 'autosi-kululaskuri' ); ?></option></select></label>
			<label><span><?php esc_html_e( 'Merkki', 'autosi-kululaskuri' ); ?></span><select name="brand"><option value=""><?php esc_html_e( 'Valitse merkki', 'autosi-kululaskuri' ); ?></option></select></label>
			<label><span><?php esc_html_e( 'Malli', 'autosi-kululaskuri' ); ?></span><select name="model" disabled><option value=""><?php esc_html_e( 'Valitse malli', 'autosi-kululaskuri' ); ?></option></select></label>
			<label><span><?php esc_html_e( 'Moottori / käyttövoima', 'autosi-kululaskuri' ); ?></span><select name="vehicle" disabled><option value=""><?php esc_html_e( 'Valitse versio', 'autosi-kululaskuri' ); ?></option></select></label>
			<label><span><?php esc_html_e( 'Ajokilometrit vuodessa', 'autosi-kululaskuri' ); ?></span><input name="distance" type="number" min="0" step="500" value="15000" inputmode="numeric"><small><?php esc_html_e( 'km / vuosi', 'autosi-kululaskuri' ); ?></small></label>
		</div>

		<div class="ak-fields ak-detailed-fields" hidden>
			<label><span><?php esc_html_e( 'Polttoaineenkulutus', 'autosi-kululaskuri' ); ?></span><input name="fuelConsumption" type="number" min="0" step="0.1"><small><?php esc_html_e( 'l / 100 km', 'autosi-kululaskuri' ); ?></small></label>
			<label><span><?php esc_html_e( 'Energiankulutus', 'autosi-kululaskuri' ); ?></span><input name="electricConsumption" type="number" min="0" step="0.1"><small><?php esc_html_e( 'kWh / 100 km', 'autosi-kululaskuri' ); ?></small></label>
			<label><span><?php esc_html_e( 'Bensiini', 'autosi-kululaskuri' ); ?></span><input name="petrolPrice" type="number" min="0" step="0.001"><small><?php esc_html_e( '€/l', 'autosi-kululaskuri' ); ?></small></label>
			<label><span><?php esc_html_e( 'Diesel', 'autosi-kululaskuri' ); ?></span><input name="dieselPrice" type="number" min="0" step="0.001"><small><?php esc_html_e( '€/l', 'autosi-kululaskuri' ); ?></small></label>
			<label><span><?php esc_html_e( 'Vakuutukset', 'autosi-kululaskuri' ); ?></span><input name="insurance" type="number" min="0" step="1"><small><?php esc_html_e( '€/vuosi', 'autosi-kululaskuri' ); ?></small></label>
			<label><span><?php esc_html_e( 'Ajoneuvovero', 'autosi-kululaskuri' ); ?></span><input name="vehicleTax" type="number" min="0" step="1"><small><?php esc_html_e( '€/vuosi, Traficom 2026 -taulukko', 'autosi-kululaskuri' ); ?></small></label>
			<label><span><?php esc_html_e( 'Käyttöönotto', 'autosi-kululaskuri' ); ?></span><input name="firstUseDate" type="date"><small><?php esc_html_e( 'täsmennä erityisesti sähköautolle', 'autosi-kululaskuri' ); ?></small></label>
			<label><span><?php esc_html_e( 'Huollon hinta', 'autosi-kululaskuri' ); ?></span><input name="serviceCost" type="number" min="0" step="1"><small><?php esc_html_e( '€/käynti', 'autosi-kululaskuri' ); ?></small></label>
			<label><span><?php esc_html_e( 'Huoltoväli', 'autosi-kululaskuri' ); ?></span><input name="serviceIntervalKm" type="number" min="1" step="1000"><small><?php esc_html_e( 'km', 'autosi-kululaskuri' ); ?></small></label>
			<label><span><?php esc_html_e( 'Huoltoväli', 'autosi-kululaskuri' ); ?></span><input name="serviceIntervalMonths" type="number" min="1" step="1"><small><?php esc_html_e( 'kuukautta', 'autosi-kululaskuri' ); ?></small></label>
			<label><span><?php esc_html_e( 'Renkaat ja vaihtotyöt', 'autosi-kululaskuri' ); ?></span><input name="tyres" type="number" min="0" step="1" value="390"><small><?php esc_html_e( '€/vuosi', 'autosi-kululaskuri' ); ?></small></label>
			<label><span><?php esc_html_e( 'Korjausvaraus', 'autosi-kululaskuri' ); ?></span><input name="repairs" type="number" min="0" step="1" value="300"><small><?php esc_html_e( '€/vuosi', 'autosi-kululaskuri' ); ?></small></label>
			<label><span><?php esc_html_e( 'Arvonalenema', 'autosi-kululaskuri' ); ?></span><input name="depreciation" type="number" min="0" step="1" value="0"><small><?php esc_html_e( '€/vuosi, valinnainen', 'autosi-kululaskuri' ); ?></small></label>
		</div>

		<fieldset class="ak-charging-fields" hidden>
			<legend><?php esc_html_e( 'Lataaminen', 'autosi-kululaskuri' ); ?></legend>
			<div class="ak-fields">
				<label><span><?php esc_html_e( 'Kotilatauksen osuus', 'autosi-kululaskuri' ); ?></span><input name="homeShare" type="number" min="0" max="100" step="1" value="75"><small><?php esc_html_e( '%', 'autosi-kululaskuri' ); ?></small></label>
				<label><span><?php esc_html_e( 'Kotilataus', 'autosi-kululaskuri' ); ?></span><input name="homePrice" type="number" min="0" step="0.001"><small><?php esc_html_e( '€/kWh', 'autosi-kululaskuri' ); ?></small></label>
				<label><span><?php esc_html_e( 'Julkinen lataus', 'autosi-kululaskuri' ); ?></span><input name="publicPrice" type="number" min="0" step="0.001"><small><?php esc_html_e( '€/kWh', 'autosi-kululaskuri' ); ?></small></label>
				<label><span><?php esc_html_e( 'Lataushäviö', 'autosi-kululaskuri' ); ?></span><input name="chargingLoss" type="number" min="0" max="50" step="1" value="10"><small><?php esc_html_e( '%', 'autosi-kululaskuri' ); ?></small></label>
				<label class="ak-phev-only"><span><?php esc_html_e( 'Sähköajon osuus', 'autosi-kululaskuri' ); ?></span><input name="electricShare" type="number" min="0" max="100" step="1" value="60"><small><?php esc_html_e( '% kilometreistä', 'autosi-kululaskuri' ); ?></small></label>
				<label><span><?php esc_html_e( 'Talvikulutuksen lisäys', 'autosi-kululaskuri' ); ?></span><input name="winterPenalty" type="number" min="0" max="100" step="1" value="10"><small><?php esc_html_e( '%', 'autosi-kululaskuri' ); ?></small></label>
			</div>
		</fieldset>

		<p class="ak-model-note" aria-live="polite"><?php esc_html_e( 'Valitse auto aloittaaksesi.', 'autosi-kululaskuri' ); ?></p>
		<aside class="ak-data-quality" data-result="dataQuality" hidden aria-live="polite"></aside>
		<div class="ak-actions"><button class="ak-primary" type="submit"><?php esc_html_e( 'Laske kulut', 'autosi-kululaskuri' ); ?></button><button class="ak-secondary" type="button" data-action="compare"><?php esc_html_e( 'Lisää vertailuun', 'autosi-kululaskuri' ); ?></button></div>
	</form>

	<div class="ak-results" hidden aria-live="polite">
		<div class="ak-kpis">
			<article><span><?php esc_html_e( 'Vuosikulut', 'autosi-kululaskuri' ); ?></span><strong data-result="annual">—</strong></article>
			<article><span><?php esc_html_e( 'Kuukaudessa', 'autosi-kululaskuri' ); ?></span><strong data-result="monthly">—</strong></article>
			<article><span><?php esc_html_e( 'Kustannus / km', 'autosi-kululaskuri' ); ?></span><strong data-result="perKm">—</strong></article>
		</div>
		<div class="ak-dashboard-grid">
			<article class="ak-panel"><h3><?php esc_html_e( 'Kulujen rakenne', 'autosi-kululaskuri' ); ?></h3><div class="ak-donut-wrap"><div class="ak-donut" data-chart="donut"><span data-result="annual">—</span></div><ul data-chart="legend"></ul></div></article>
			<article class="ak-panel"><h3><?php esc_html_e( 'Mitä maksat tänä vuonna?', 'autosi-kululaskuri' ); ?></h3><dl class="ak-breakdown" data-result="breakdown"></dl></article>
		</div>
		<article class="ak-panel ak-formula-panel"><h3><?php esc_html_e( 'Laskelman perusteet', 'autosi-kululaskuri' ); ?></h3><div data-result="formulas"></div></article>
	</div>

	<section class="ak-comparison" hidden>
		<div class="ak-section-heading"><div><p class="ak-eyebrow"><?php esc_html_e( 'VERTAILU', 'autosi-kululaskuri' ); ?></p><h3><?php esc_html_e( 'Autot rinnakkain', 'autosi-kululaskuri' ); ?></h3></div><button class="ak-text-button" type="button" data-action="clear-comparison"><?php esc_html_e( 'Tyhjennä', 'autosi-kululaskuri' ); ?></button></div>
		<div class="ak-comparison-chart" data-chart="comparison" aria-label="<?php esc_attr_e( 'Vuosikulut autoittain', 'autosi-kululaskuri' ); ?>"></div>
		<aside class="ak-comparison-assumptions" data-result="comparisonAssumptions" aria-live="polite"></aside>
		<div class="ak-table-wrap" role="region" aria-label="<?php esc_attr_e( 'Autokohtaisten kulujen vertailu', 'autosi-kululaskuri' ); ?>" tabindex="0"><table class="ak-comparison-table"><thead><tr data-result="comparisonHead"></tr></thead><tbody data-result="comparisonRows"></tbody></table></div>
	</section>
</section>
