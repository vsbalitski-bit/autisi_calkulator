<?php
/**
 * Uninstall routine for Autosi Kululaskuri.
 *
 * Removes the settings and catalog options (including the precomputed index and any
 * cached REST payloads) so deleting the plugin leaves no leftover data behind.
 */

defined( 'WP_UNINSTALL_PLUGIN' ) || exit;

/**
 * Delete this plugin's data for the current site.
 */
function autosi_kululaskuri_uninstall_site() {
	delete_option( 'autosi_kululaskuri_settings' );
	delete_option( 'autosi_kululaskuri_catalog' );
	delete_option( 'autosi_kululaskuri_catalog_index' );
	delete_option( 'autosi_kululaskuri_catalog_meta' );

	global $wpdb;
	$like         = $wpdb->esc_like( '_transient_autosi_kl_' ) . '%';
	$like_timeout = $wpdb->esc_like( '_transient_timeout_autosi_kl_' ) . '%';
	// phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching
	$wpdb->query( $wpdb->prepare( "DELETE FROM {$wpdb->options} WHERE option_name LIKE %s OR option_name LIKE %s", $like, $like_timeout ) );
}

if ( is_multisite() ) {
	foreach ( get_sites( array( 'fields' => 'ids' ) ) as $autosi_site_id ) {
		switch_to_blog( $autosi_site_id );
		autosi_kululaskuri_uninstall_site();
		restore_current_blog();
	}
} else {
	autosi_kululaskuri_uninstall_site();
}
