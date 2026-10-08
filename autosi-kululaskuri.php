<?php
/**
 * Plugin Name: Autosi Kululaskuri
 * Description: Finnish annual car-cost calculator with simple and detailed modes, electric charging logic, comparison, and an admin-managed model catalogue.
 * Version: 0.5.3
 * Requires at least: 6.0
 * Requires PHP: 7.4
 * Author: Autosi Kululaskuri
 * License: GPLv2 or later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain: autosi-kululaskuri
 */

defined( 'ABSPATH' ) || exit;

define( 'AUTOSI_KULULASKURI_VERSION', '0.5.3' );
define( 'AUTOSI_KULULASKURI_FILE', __FILE__ );
define( 'AUTOSI_KULULASKURI_PATH', plugin_dir_path( __FILE__ ) );
define( 'AUTOSI_KULULASKURI_URL', plugin_dir_url( __FILE__ ) );

require_once AUTOSI_KULULASKURI_PATH . 'includes/class-autosi-kululaskuri.php';

register_activation_hook( __FILE__, array( 'Autosi_Kululaskuri', 'activate' ) );

Autosi_Kululaskuri::instance();
