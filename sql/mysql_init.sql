CREATE DATABASE IF NOT EXISTS bnb_wallet_vault
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'bnb_vault_user'@'localhost'
  IDENTIFIED BY 'change-me-now';

GRANT ALL PRIVILEGES
  ON bnb_wallet_vault.*
  TO 'bnb_vault_user'@'localhost';

FLUSH PRIVILEGES;

USE bnb_wallet_vault;

CREATE TABLE IF NOT EXISTS wallet_entries (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  label VARCHAR(120) NOT NULL,
  wallet_address VARCHAR(120) NOT NULL,
  encrypted_private_key TEXT NOT NULL,
  salt VARCHAR(64) NOT NULL,
  nonce VARCHAR(64) NOT NULL,
  notes TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_wallet_entries_wallet_address (wallet_address),
  KEY ix_wallet_entries_created_at (created_at)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS transfer_entries (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  wallet_id INT NOT NULL,
  wallet_label VARCHAR(120) NOT NULL,
  from_wallet_address VARCHAR(120) NOT NULL,
  to_wallet_address VARCHAR(120) NOT NULL,
  amount_bnb DECIMAL(36,18) NOT NULL,
  asset_symbol VARCHAR(20) NOT NULL DEFAULT 'BNB',
  token_contract VARCHAR(120) NULL,
  token_decimals INT NULL,
  tx_hash VARCHAR(90) NOT NULL,
  chain_id INT NOT NULL,
  gas_limit INT NOT NULL,
  gas_price_wei VARCHAR(40) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_transfer_entries_tx_hash (tx_hash),
  KEY ix_transfer_entries_wallet_id (wallet_id),
  KEY ix_transfer_entries_created_at (created_at)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;
