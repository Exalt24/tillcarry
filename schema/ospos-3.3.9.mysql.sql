-- Final schema of Open Source Point of Sale 3.3.9 (CodeIgniter 3), MySQL form.
-- Produced by running the project's own migrations (see schema/PROVENANCE.md), then
-- mysqldump --no-data. Source: https://github.com/opensourcepos/opensourcepos at commit
-- c00ff28d10f25c2638a65cbfbbcd08b75a83c59f (tag 3.3.9). MIT licence, see ../NOTICE.
-- Table definitions only; no data.

CREATE TABLE `ospos_app_config` (
  `key` varchar(50) NOT NULL,
  `value` varchar(500) NOT NULL,
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_attribute_definitions` (
  `definition_id` int NOT NULL AUTO_INCREMENT,
  `definition_name` varchar(255) NOT NULL,
  `definition_type` varchar(45) NOT NULL,
  `definition_unit` varchar(16) DEFAULT NULL,
  `definition_flags` tinyint(1) NOT NULL,
  `definition_fk` int DEFAULT NULL,
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`definition_id`),
  KEY `definition_fk` (`definition_fk`),
  KEY `definition_name` (`definition_name`),
  KEY `definition_type` (`definition_type`),
  CONSTRAINT `fk_ospos_attribute_definitions_ibfk_1` FOREIGN KEY (`definition_fk`) REFERENCES `ospos_attribute_definitions` (`definition_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_attribute_links` (
  `attribute_id` int DEFAULT NULL,
  `definition_id` int NOT NULL,
  `item_id` int DEFAULT NULL,
  `sale_id` int DEFAULT NULL,
  `receiving_id` int DEFAULT NULL,
  UNIQUE KEY `attribute_links_uq1` (`attribute_id`,`definition_id`,`item_id`,`sale_id`,`receiving_id`),
  UNIQUE KEY `attribute_links_uq2` (`item_id`,`sale_id`,`receiving_id`,`definition_id`,`attribute_id`),
  KEY `attribute_id` (`attribute_id`),
  KEY `definition_id` (`definition_id`),
  KEY `item_id` (`item_id`),
  KEY `sale_id` (`sale_id`),
  KEY `receiving_id` (`receiving_id`),
  CONSTRAINT `ospos_attribute_links_ibfk_1` FOREIGN KEY (`definition_id`) REFERENCES `ospos_attribute_definitions` (`definition_id`) ON DELETE CASCADE,
  CONSTRAINT `ospos_attribute_links_ibfk_2` FOREIGN KEY (`attribute_id`) REFERENCES `ospos_attribute_values` (`attribute_id`) ON DELETE CASCADE,
  CONSTRAINT `ospos_attribute_links_ibfk_3` FOREIGN KEY (`item_id`) REFERENCES `ospos_items` (`item_id`),
  CONSTRAINT `ospos_attribute_links_ibfk_4` FOREIGN KEY (`receiving_id`) REFERENCES `ospos_receivings` (`receiving_id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `ospos_attribute_links_ibfk_5` FOREIGN KEY (`sale_id`) REFERENCES `ospos_sales` (`sale_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_attribute_values` (
  `attribute_id` int NOT NULL AUTO_INCREMENT,
  `attribute_value` varchar(255) DEFAULT NULL,
  `attribute_date` date DEFAULT NULL,
  `attribute_decimal` decimal(7,3) DEFAULT NULL,
  PRIMARY KEY (`attribute_id`),
  UNIQUE KEY `attribute_value` (`attribute_value`),
  UNIQUE KEY `attribute_date` (`attribute_date`),
  UNIQUE KEY `attribute_decimal` (`attribute_decimal`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_cash_up` (
  `cashup_id` int NOT NULL AUTO_INCREMENT,
  `open_date` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `close_date` timestamp NULL DEFAULT NULL,
  `open_amount_cash` decimal(15,2) NOT NULL,
  `transfer_amount_cash` decimal(15,2) NOT NULL,
  `note` int NOT NULL,
  `closed_amount_cash` decimal(15,2) NOT NULL,
  `closed_amount_card` decimal(15,2) NOT NULL,
  `closed_amount_check` decimal(15,2) NOT NULL,
  `closed_amount_total` decimal(15,2) NOT NULL,
  `description` varchar(255) NOT NULL,
  `open_employee_id` int NOT NULL,
  `close_employee_id` int NOT NULL,
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  `closed_amount_due` decimal(15,2) NOT NULL,
  PRIMARY KEY (`cashup_id`),
  KEY `open_employee_id` (`open_employee_id`),
  KEY `close_employee_id` (`close_employee_id`),
  CONSTRAINT `ospos_cash_up_ibfk_1` FOREIGN KEY (`open_employee_id`) REFERENCES `ospos_employees` (`person_id`),
  CONSTRAINT `ospos_cash_up_ibfk_2` FOREIGN KEY (`close_employee_id`) REFERENCES `ospos_employees` (`person_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_customers` (
  `person_id` int NOT NULL,
  `company_name` varchar(255) DEFAULT NULL,
  `account_number` varchar(255) DEFAULT NULL,
  `taxable` tinyint(1) NOT NULL DEFAULT '1',
  `tax_id` varchar(32) NOT NULL DEFAULT '',
  `sales_tax_code_id` int DEFAULT NULL,
  `discount` decimal(15,2) NOT NULL DEFAULT '0.00',
  `discount_type` tinyint(1) NOT NULL DEFAULT '0',
  `package_id` int DEFAULT NULL,
  `points` int DEFAULT NULL,
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  `date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `employee_id` int NOT NULL,
  `consent` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`person_id`),
  UNIQUE KEY `account_number` (`account_number`),
  KEY `person_id` (`person_id`),
  KEY `package_id` (`package_id`),
  KEY `sales_tax_code_id` (`sales_tax_code_id`),
  KEY `company_name` (`company_name`),
  CONSTRAINT `ospos_customers_ibfk_1` FOREIGN KEY (`person_id`) REFERENCES `ospos_people` (`person_id`),
  CONSTRAINT `ospos_customers_ibfk_2` FOREIGN KEY (`package_id`) REFERENCES `ospos_customers_packages` (`package_id`),
  CONSTRAINT `ospos_customers_ibfk_3` FOREIGN KEY (`sales_tax_code_id`) REFERENCES `ospos_tax_codes` (`tax_code_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_customers_packages` (
  `package_id` int NOT NULL AUTO_INCREMENT,
  `package_name` varchar(255) DEFAULT NULL,
  `points_percent` float NOT NULL DEFAULT '0',
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`package_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_customers_points` (
  `id` int NOT NULL AUTO_INCREMENT,
  `person_id` int NOT NULL,
  `package_id` int NOT NULL,
  `sale_id` int NOT NULL,
  `points_earned` int NOT NULL,
  PRIMARY KEY (`id`),
  KEY `person_id` (`person_id`),
  KEY `package_id` (`package_id`),
  KEY `sale_id` (`sale_id`),
  CONSTRAINT `ospos_customers_points_ibfk_1` FOREIGN KEY (`person_id`) REFERENCES `ospos_customers` (`person_id`),
  CONSTRAINT `ospos_customers_points_ibfk_2` FOREIGN KEY (`package_id`) REFERENCES `ospos_customers_packages` (`package_id`),
  CONSTRAINT `ospos_customers_points_ibfk_3` FOREIGN KEY (`sale_id`) REFERENCES `ospos_sales` (`sale_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_dinner_tables` (
  `dinner_table_id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(30) NOT NULL,
  `status` tinyint(1) NOT NULL DEFAULT '0',
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`dinner_table_id`),
  KEY `status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_employees` (
  `username` varchar(255) NOT NULL,
  `password` varchar(255) NOT NULL,
  `person_id` int NOT NULL,
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  `hash_version` tinyint(1) NOT NULL DEFAULT '2',
  `language` varchar(48) DEFAULT NULL,
  `language_code` varchar(8) DEFAULT NULL,
  PRIMARY KEY (`person_id`),
  UNIQUE KEY `username` (`username`),
  KEY `person_id` (`person_id`),
  CONSTRAINT `ospos_employees_ibfk_1` FOREIGN KEY (`person_id`) REFERENCES `ospos_people` (`person_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_expense_categories` (
  `expense_category_id` int NOT NULL AUTO_INCREMENT,
  `category_name` varchar(255) DEFAULT NULL,
  `category_description` varchar(255) NOT NULL,
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`expense_category_id`),
  UNIQUE KEY `category_name` (`category_name`),
  KEY `category_description` (`category_description`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_expenses` (
  `expense_id` int NOT NULL AUTO_INCREMENT,
  `date` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `amount` decimal(15,2) NOT NULL,
  `payment_type` varchar(40) NOT NULL,
  `expense_category_id` int NOT NULL,
  `description` varchar(255) NOT NULL,
  `employee_id` int NOT NULL,
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  `supplier_tax_code` varchar(255) DEFAULT NULL,
  `tax_amount` decimal(15,2) DEFAULT NULL,
  `supplier_id` int DEFAULT NULL,
  PRIMARY KEY (`expense_id`),
  KEY `expense_category_id` (`expense_category_id`),
  KEY `employee_id` (`employee_id`),
  KEY `ospos_expenses_ibfk_3` (`supplier_id`),
  KEY `date` (`date`),
  KEY `payment_type` (`payment_type`),
  KEY `amount` (`amount`),
  CONSTRAINT `ospos_expenses_ibfk_1` FOREIGN KEY (`expense_category_id`) REFERENCES `ospos_expense_categories` (`expense_category_id`),
  CONSTRAINT `ospos_expenses_ibfk_2` FOREIGN KEY (`employee_id`) REFERENCES `ospos_employees` (`person_id`),
  CONSTRAINT `ospos_expenses_ibfk_3` FOREIGN KEY (`supplier_id`) REFERENCES `ospos_suppliers` (`person_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_giftcards` (
  `record_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `giftcard_id` int NOT NULL AUTO_INCREMENT,
  `giftcard_number` varchar(255) DEFAULT NULL,
  `value` decimal(15,2) NOT NULL,
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  `person_id` int DEFAULT NULL,
  PRIMARY KEY (`giftcard_id`),
  UNIQUE KEY `giftcard_number` (`giftcard_number`),
  KEY `person_id` (`person_id`),
  CONSTRAINT `ospos_giftcards_ibfk_1` FOREIGN KEY (`person_id`) REFERENCES `ospos_people` (`person_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_grants` (
  `permission_id` varchar(255) NOT NULL,
  `person_id` int NOT NULL,
  `menu_group` varchar(32) DEFAULT 'home',
  PRIMARY KEY (`permission_id`,`person_id`),
  KEY `ospos_grants_ibfk_2` (`person_id`),
  CONSTRAINT `ospos_grants_ibfk_1` FOREIGN KEY (`permission_id`) REFERENCES `ospos_permissions` (`permission_id`) ON DELETE CASCADE,
  CONSTRAINT `ospos_grants_ibfk_2` FOREIGN KEY (`person_id`) REFERENCES `ospos_employees` (`person_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_inventory` (
  `trans_id` int NOT NULL AUTO_INCREMENT,
  `trans_items` int NOT NULL DEFAULT '0',
  `trans_user` int NOT NULL DEFAULT '0',
  `trans_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `trans_comment` text NOT NULL,
  `trans_location` int NOT NULL,
  `trans_inventory` decimal(15,3) NOT NULL DEFAULT '0.000',
  PRIMARY KEY (`trans_id`),
  KEY `trans_items` (`trans_items`),
  KEY `trans_user` (`trans_user`),
  KEY `trans_location` (`trans_location`),
  KEY `trans_date` (`trans_date`),
  CONSTRAINT `ospos_inventory_ibfk_1` FOREIGN KEY (`trans_items`) REFERENCES `ospos_items` (`item_id`),
  CONSTRAINT `ospos_inventory_ibfk_2` FOREIGN KEY (`trans_user`) REFERENCES `ospos_employees` (`person_id`),
  CONSTRAINT `ospos_inventory_ibfk_3` FOREIGN KEY (`trans_location`) REFERENCES `ospos_stock_locations` (`location_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_item_kit_items` (
  `item_kit_id` int NOT NULL,
  `item_id` int NOT NULL,
  `quantity` decimal(15,3) NOT NULL,
  `kit_sequence` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`item_kit_id`,`item_id`,`quantity`),
  KEY `ospos_item_kit_items_ibfk_2` (`item_id`),
  CONSTRAINT `ospos_item_kit_items_ibfk_1` FOREIGN KEY (`item_kit_id`) REFERENCES `ospos_item_kits` (`item_kit_id`) ON DELETE CASCADE,
  CONSTRAINT `ospos_item_kit_items_ibfk_2` FOREIGN KEY (`item_id`) REFERENCES `ospos_items` (`item_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_item_kits` (
  `item_kit_id` int NOT NULL AUTO_INCREMENT,
  `item_kit_number` varchar(255) DEFAULT NULL,
  `name` varchar(255) NOT NULL,
  `item_id` int NOT NULL DEFAULT '0',
  `kit_discount` decimal(15,2) NOT NULL DEFAULT '0.00',
  `kit_discount_type` tinyint(1) NOT NULL DEFAULT '0',
  `price_option` tinyint(1) NOT NULL DEFAULT '0',
  `print_option` tinyint(1) NOT NULL DEFAULT '0',
  `description` varchar(255) NOT NULL,
  PRIMARY KEY (`item_kit_id`),
  KEY `item_kit_number` (`item_kit_number`),
  KEY `name` (`name`,`description`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_item_quantities` (
  `item_id` int NOT NULL,
  `location_id` int NOT NULL,
  `quantity` decimal(15,3) NOT NULL DEFAULT '0.000',
  PRIMARY KEY (`item_id`,`location_id`),
  KEY `item_id` (`item_id`),
  KEY `location_id` (`location_id`),
  CONSTRAINT `ospos_item_quantities_ibfk_1` FOREIGN KEY (`item_id`) REFERENCES `ospos_items` (`item_id`),
  CONSTRAINT `ospos_item_quantities_ibfk_2` FOREIGN KEY (`location_id`) REFERENCES `ospos_stock_locations` (`location_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_items` (
  `name` varchar(255) NOT NULL,
  `category` varchar(255) NOT NULL,
  `supplier_id` int DEFAULT NULL,
  `item_number` varchar(255) DEFAULT NULL,
  `description` varchar(255) NOT NULL,
  `cost_price` decimal(15,2) NOT NULL,
  `unit_price` decimal(15,2) NOT NULL,
  `reorder_level` decimal(15,3) NOT NULL DEFAULT '0.000',
  `receiving_quantity` decimal(15,3) NOT NULL DEFAULT '1.000',
  `item_id` int NOT NULL AUTO_INCREMENT,
  `pic_filename` varchar(255) DEFAULT NULL,
  `allow_alt_description` tinyint(1) NOT NULL,
  `is_serialized` tinyint(1) NOT NULL,
  `stock_type` tinyint(1) NOT NULL DEFAULT '0',
  `item_type` tinyint(1) NOT NULL DEFAULT '0',
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  `tax_category_id` int DEFAULT NULL,
  `qty_per_pack` decimal(15,3) NOT NULL DEFAULT '1.000',
  `pack_name` varchar(8) DEFAULT 'Each',
  `low_sell_item_id` int DEFAULT '0',
  `hsn_code` varchar(32) NOT NULL DEFAULT '',
  PRIMARY KEY (`item_id`),
  UNIQUE KEY `items_uq1` (`supplier_id`,`item_id`,`deleted`,`item_type`),
  KEY `item_number` (`item_number`),
  KEY `supplier_id` (`supplier_id`),
  KEY `deleted` (`deleted`,`item_type`),
  CONSTRAINT `ospos_items_ibfk_1` FOREIGN KEY (`supplier_id`) REFERENCES `ospos_suppliers` (`person_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_items_taxes` (
  `item_id` int NOT NULL,
  `name` varchar(255) NOT NULL,
  `percent` decimal(15,3) NOT NULL,
  PRIMARY KEY (`item_id`,`name`,`percent`),
  CONSTRAINT `ospos_items_taxes_ibfk_1` FOREIGN KEY (`item_id`) REFERENCES `ospos_items` (`item_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_migrations` (
  `version` bigint NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_modules` (
  `name_lang_key` varchar(255) NOT NULL,
  `desc_lang_key` varchar(255) NOT NULL,
  `sort` int NOT NULL,
  `module_id` varchar(255) NOT NULL,
  PRIMARY KEY (`module_id`),
  UNIQUE KEY `desc_lang_key` (`desc_lang_key`),
  UNIQUE KEY `name_lang_key` (`name_lang_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_people` (
  `first_name` varchar(255) NOT NULL,
  `last_name` varchar(255) NOT NULL,
  `gender` int DEFAULT NULL,
  `phone_number` varchar(255) NOT NULL,
  `email` varchar(255) NOT NULL,
  `address_1` varchar(255) NOT NULL,
  `address_2` varchar(255) NOT NULL,
  `city` varchar(255) NOT NULL,
  `state` varchar(255) NOT NULL,
  `zip` varchar(255) NOT NULL,
  `country` varchar(255) NOT NULL,
  `comments` text NOT NULL,
  `person_id` int NOT NULL AUTO_INCREMENT,
  PRIMARY KEY (`person_id`),
  KEY `email` (`email`),
  KEY `first_name` (`first_name`,`last_name`,`email`,`phone_number`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_permissions` (
  `permission_id` varchar(255) NOT NULL,
  `module_id` varchar(255) NOT NULL,
  `location_id` int DEFAULT NULL,
  PRIMARY KEY (`permission_id`),
  KEY `module_id` (`module_id`),
  KEY `ospos_permissions_ibfk_2` (`location_id`),
  CONSTRAINT `ospos_permissions_ibfk_1` FOREIGN KEY (`module_id`) REFERENCES `ospos_modules` (`module_id`) ON DELETE CASCADE,
  CONSTRAINT `ospos_permissions_ibfk_2` FOREIGN KEY (`location_id`) REFERENCES `ospos_stock_locations` (`location_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_receivings` (
  `receiving_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `supplier_id` int DEFAULT NULL,
  `employee_id` int NOT NULL DEFAULT '0',
  `comment` text,
  `receiving_id` int NOT NULL AUTO_INCREMENT,
  `payment_type` varchar(20) DEFAULT NULL,
  `reference` varchar(32) DEFAULT NULL,
  PRIMARY KEY (`receiving_id`),
  KEY `supplier_id` (`supplier_id`),
  KEY `employee_id` (`employee_id`),
  KEY `reference` (`reference`),
  KEY `receiving_time` (`receiving_time`),
  CONSTRAINT `ospos_receivings_ibfk_1` FOREIGN KEY (`employee_id`) REFERENCES `ospos_employees` (`person_id`),
  CONSTRAINT `ospos_receivings_ibfk_2` FOREIGN KEY (`supplier_id`) REFERENCES `ospos_suppliers` (`person_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_receivings_items` (
  `receiving_id` int NOT NULL DEFAULT '0',
  `item_id` int NOT NULL DEFAULT '0',
  `description` varchar(30) DEFAULT NULL,
  `serialnumber` varchar(30) DEFAULT NULL,
  `line` int NOT NULL,
  `quantity_purchased` decimal(15,3) NOT NULL DEFAULT '0.000',
  `item_cost_price` decimal(15,2) NOT NULL,
  `item_unit_price` decimal(15,2) NOT NULL,
  `discount` decimal(15,2) NOT NULL DEFAULT '0.00',
  `discount_type` tinyint(1) NOT NULL DEFAULT '0',
  `item_location` int NOT NULL,
  `receiving_quantity` decimal(15,3) NOT NULL DEFAULT '1.000',
  PRIMARY KEY (`receiving_id`,`item_id`,`line`),
  KEY `item_id` (`item_id`),
  CONSTRAINT `ospos_receivings_items_ibfk_1` FOREIGN KEY (`item_id`) REFERENCES `ospos_items` (`item_id`),
  CONSTRAINT `ospos_receivings_items_ibfk_2` FOREIGN KEY (`receiving_id`) REFERENCES `ospos_receivings` (`receiving_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_sales` (
  `sale_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `customer_id` int DEFAULT NULL,
  `employee_id` int NOT NULL DEFAULT '0',
  `comment` text,
  `invoice_number` varchar(32) DEFAULT NULL,
  `quote_number` varchar(32) DEFAULT NULL,
  `sale_id` int NOT NULL AUTO_INCREMENT,
  `sale_status` tinyint(1) NOT NULL DEFAULT '0',
  `dinner_table_id` int DEFAULT NULL,
  `work_order_number` varchar(32) DEFAULT NULL,
  `sale_type` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`sale_id`),
  UNIQUE KEY `invoice_number` (`invoice_number`),
  KEY `customer_id` (`customer_id`),
  KEY `employee_id` (`employee_id`),
  KEY `sale_time` (`sale_time`),
  KEY `dinner_table_id` (`dinner_table_id`),
  CONSTRAINT `ospos_sales_ibfk_1` FOREIGN KEY (`employee_id`) REFERENCES `ospos_employees` (`person_id`),
  CONSTRAINT `ospos_sales_ibfk_2` FOREIGN KEY (`customer_id`) REFERENCES `ospos_customers` (`person_id`),
  CONSTRAINT `ospos_sales_ibfk_3` FOREIGN KEY (`dinner_table_id`) REFERENCES `ospos_dinner_tables` (`dinner_table_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_sales_items` (
  `sale_id` int NOT NULL DEFAULT '0',
  `item_id` int NOT NULL DEFAULT '0',
  `description` varchar(255) DEFAULT NULL,
  `serialnumber` varchar(30) DEFAULT NULL,
  `line` int NOT NULL DEFAULT '0',
  `quantity_purchased` decimal(15,3) NOT NULL DEFAULT '0.000',
  `item_cost_price` decimal(15,2) NOT NULL,
  `item_unit_price` decimal(15,2) NOT NULL,
  `discount` decimal(15,2) NOT NULL DEFAULT '0.00',
  `discount_type` tinyint(1) NOT NULL DEFAULT '0',
  `item_location` int NOT NULL,
  `print_option` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`sale_id`,`item_id`,`line`),
  KEY `sale_id` (`sale_id`),
  KEY `item_id` (`item_id`),
  KEY `item_location` (`item_location`),
  CONSTRAINT `ospos_sales_items_ibfk_1` FOREIGN KEY (`item_id`) REFERENCES `ospos_items` (`item_id`),
  CONSTRAINT `ospos_sales_items_ibfk_2` FOREIGN KEY (`sale_id`) REFERENCES `ospos_sales` (`sale_id`),
  CONSTRAINT `ospos_sales_items_ibfk_3` FOREIGN KEY (`item_location`) REFERENCES `ospos_stock_locations` (`location_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_sales_items_taxes` (
  `sale_id` int NOT NULL,
  `item_id` int NOT NULL,
  `line` int NOT NULL DEFAULT '0',
  `name` varchar(255) NOT NULL,
  `percent` decimal(15,4) NOT NULL DEFAULT '0.0000',
  `tax_type` tinyint(1) NOT NULL DEFAULT '0',
  `rounding_code` tinyint(1) NOT NULL DEFAULT '0',
  `cascade_sequence` tinyint(1) NOT NULL DEFAULT '0',
  `item_tax_amount` decimal(15,4) NOT NULL DEFAULT '0.0000',
  `sales_tax_code_id` int DEFAULT NULL,
  `jurisdiction_id` int DEFAULT NULL,
  `tax_category_id` int DEFAULT NULL,
  PRIMARY KEY (`sale_id`,`item_id`,`line`,`name`,`percent`),
  KEY `sale_id` (`sale_id`),
  KEY `item_id` (`item_id`),
  CONSTRAINT `ospos_sales_items_taxes_ibfk_1` FOREIGN KEY (`sale_id`) REFERENCES `ospos_sales_items` (`sale_id`),
  CONSTRAINT `ospos_sales_items_taxes_ibfk_2` FOREIGN KEY (`item_id`) REFERENCES `ospos_items` (`item_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_sales_payments` (
  `payment_id` int NOT NULL AUTO_INCREMENT,
  `sale_id` int NOT NULL,
  `payment_type` varchar(40) NOT NULL,
  `payment_amount` decimal(15,2) NOT NULL,
  `cash_refund` decimal(15,2) NOT NULL DEFAULT '0.00',
  `cash_adjustment` tinyint NOT NULL DEFAULT '0',
  `employee_id` int DEFAULT NULL,
  `payment_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `reference_code` varchar(40) NOT NULL DEFAULT '',
  PRIMARY KEY (`payment_id`),
  KEY `payment_sale` (`sale_id`,`payment_type`),
  KEY `employee_id` (`employee_id`),
  KEY `payment_time` (`payment_time`),
  CONSTRAINT `ospos_sales_payments_ibfk_1` FOREIGN KEY (`sale_id`) REFERENCES `ospos_sales` (`sale_id`),
  CONSTRAINT `ospos_sales_payments_ibfk_2` FOREIGN KEY (`employee_id`) REFERENCES `ospos_employees` (`person_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_sales_reward_points` (
  `id` int NOT NULL AUTO_INCREMENT,
  `sale_id` int NOT NULL,
  `earned` float NOT NULL,
  `used` float NOT NULL,
  PRIMARY KEY (`id`),
  KEY `sale_id` (`sale_id`),
  CONSTRAINT `ospos_sales_reward_points_ibfk_1` FOREIGN KEY (`sale_id`) REFERENCES `ospos_sales` (`sale_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_sales_taxes` (
  `sales_taxes_id` int NOT NULL AUTO_INCREMENT,
  `sale_id` int NOT NULL,
  `jurisdiction_id` int DEFAULT NULL,
  `tax_category_id` int DEFAULT NULL,
  `tax_type` smallint NOT NULL,
  `tax_group` varchar(32) NOT NULL,
  `sale_tax_basis` decimal(15,4) NOT NULL,
  `sale_tax_amount` decimal(15,4) NOT NULL,
  `print_sequence` tinyint(1) NOT NULL DEFAULT '0',
  `name` varchar(255) NOT NULL,
  `tax_rate` decimal(15,4) NOT NULL,
  `sales_tax_code_id` int DEFAULT NULL,
  `rounding_code` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`sales_taxes_id`),
  KEY `print_sequence` (`sale_id`,`print_sequence`,`tax_group`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_sessions` (
  `id` varchar(40) NOT NULL,
  `ip_address` varchar(45) NOT NULL,
  `timestamp` int unsigned NOT NULL DEFAULT '0',
  `data` mediumblob NOT NULL,
  KEY `ci_sessions_timestamp` (`timestamp`),
  KEY `id` (`id`),
  KEY `ip_address` (`ip_address`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_stock_locations` (
  `location_id` int NOT NULL AUTO_INCREMENT,
  `location_name` varchar(255) DEFAULT NULL,
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`location_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_suppliers` (
  `person_id` int NOT NULL,
  `company_name` varchar(255) NOT NULL,
  `agency_name` varchar(255) NOT NULL,
  `account_number` varchar(255) DEFAULT NULL,
  `tax_id` varchar(32) NOT NULL DEFAULT '',
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  `category` tinyint(1) NOT NULL,
  PRIMARY KEY (`person_id`),
  UNIQUE KEY `account_number` (`account_number`),
  KEY `person_id` (`person_id`),
  KEY `category` (`category`),
  KEY `company_name` (`company_name`,`deleted`),
  CONSTRAINT `ospos_suppliers_ibfk_1` FOREIGN KEY (`person_id`) REFERENCES `ospos_people` (`person_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_tax_categories` (
  `tax_category_id` int NOT NULL AUTO_INCREMENT,
  `tax_category` varchar(32) NOT NULL,
  `tax_group_sequence` tinyint(1) NOT NULL,
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`tax_category_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_tax_codes` (
  `tax_code_id` int NOT NULL AUTO_INCREMENT,
  `tax_code` varchar(32) NOT NULL,
  `tax_code_name` varchar(255) NOT NULL DEFAULT '',
  `city` varchar(255) NOT NULL DEFAULT '',
  `state` varchar(255) NOT NULL DEFAULT '',
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`tax_code_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_tax_jurisdictions` (
  `jurisdiction_id` int NOT NULL AUTO_INCREMENT,
  `jurisdiction_name` varchar(255) DEFAULT NULL,
  `tax_group` varchar(32) NOT NULL,
  `tax_type` smallint NOT NULL,
  `reporting_authority` varchar(255) DEFAULT NULL,
  `tax_group_sequence` tinyint(1) NOT NULL DEFAULT '0',
  `cascade_sequence` tinyint(1) NOT NULL DEFAULT '0',
  `deleted` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`jurisdiction_id`),
  UNIQUE KEY `tax_jurisdictions_uq1` (`tax_group`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `ospos_tax_rates` (
  `tax_rate_id` int NOT NULL AUTO_INCREMENT,
  `rate_tax_code_id` int NOT NULL,
  `rate_tax_category_id` int NOT NULL,
  `rate_jurisdiction_id` int NOT NULL,
  `tax_rate` decimal(15,4) NOT NULL DEFAULT '0.0000',
  `tax_rounding_code` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`tax_rate_id`),
  KEY `rate_tax_category_id` (`rate_tax_category_id`),
  KEY `rate_tax_code_id` (`rate_tax_code_id`),
  KEY `rate_jurisdiction_id` (`rate_jurisdiction_id`),
  CONSTRAINT `ospos_tax_rates_ibfk_1` FOREIGN KEY (`rate_tax_category_id`) REFERENCES `ospos_tax_categories` (`tax_category_id`),
  CONSTRAINT `ospos_tax_rates_ibfk_2` FOREIGN KEY (`rate_tax_code_id`) REFERENCES `ospos_tax_codes` (`tax_code_id`),
  CONSTRAINT `ospos_tax_rates_ibfk_3` FOREIGN KEY (`rate_jurisdiction_id`) REFERENCES `ospos_tax_jurisdictions` (`jurisdiction_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
