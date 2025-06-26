#!/usr/bin/env python3
"""
Migration script to transfer Home Key data from file-based repository to API repository.
This script should be run once to migrate existing data.
"""

import json
import logging
import sys
from pathlib import Path

from repository import Repository
from api_repository import APIRepository


def load_configuration(path="configuration.json") -> dict:
    """Load configuration from JSON file"""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Configuration file {path} not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in configuration file: {e}")
        sys.exit(1)


def configure_logging():
    """Set up logging for the migration"""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)8s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    return logging.getLogger()


def migrate_data(config: dict, log):
    """Perform the migration from file to API repository"""
    homekey_config = config.get("homekey", {})
    
    # Get file path for file-based repository
    file_path = homekey_config.get("persist", "homekey.json")
    
    # Get API URL for API repository
    api_base_url = homekey_config.get("api_base_url")
    if not api_base_url:
        log.error("No api_base_url found in configuration")
        return False
    
    # Check if file exists
    if not Path(file_path).exists():
        log.warning(f"File {file_path} does not exist. Nothing to migrate.")
        return True
    
    log.info(f"Starting migration from {file_path} to {api_base_url}")
    
    try:
        # Create file-based repository
        log.info("Loading data from file-based repository...")
        file_repo = Repository(file_path)
        
        # Create API repository
        log.info("Connecting to API repository...")
        api_secret = homekey_config.get("api_secret")
        api_repo = APIRepository(api_base_url, api_secret)
        
        # Get all data from file repository
        reader_private_key = file_repo.get_reader_private_key()
        reader_identifier = file_repo.get_reader_identifier()
        all_issuers = file_repo.get_all_issuers()
        
        log.info(f"Found {len(all_issuers)} issuers in file repository")
        log.info(f"Reader private key: {reader_private_key.hex()[:16]}...")
        log.info(f"Reader identifier: {reader_identifier.hex()}")
        
        # Migrate reader configuration
        log.info("Migrating reader configuration...")
        api_repo.set_reader_private_key(reader_private_key)
        api_repo.set_reader_identifier(reader_identifier)
        
        # Migrate issuers
        if all_issuers:
            log.info("Migrating issuers...")
            api_repo.upsert_issuers(all_issuers)
            
            # Log details about migrated issuers
            for issuer in all_issuers:
                log.info(f"Migrated issuer {issuer.id.hex()[:16]}... with {len(issuer.endpoints)} endpoints")
        
        log.info("Migration completed successfully!")
        
        # Verify migration by checking API repository
        log.info("Verifying migration...")
        api_issuers = api_repo.get_all_issuers()
        api_reader_key = api_repo.get_reader_private_key()
        api_reader_id = api_repo.get_reader_identifier()
        
        if (len(api_issuers) == len(all_issuers) and 
            api_reader_key == reader_private_key and 
            api_reader_id == reader_identifier):
            log.info("✓ Migration verification successful!")
            return True
        else:
            log.error("✗ Migration verification failed!")
            log.error(f"Expected {len(all_issuers)} issuers, found {len(api_issuers)}")
            return False
            
    except Exception as e:
        log.exception(f"Migration failed: {e}")
        return False


def main():
    """Main migration function"""
    log = configure_logging()
    
    log.info("Home Key Repository Migration Tool")
    log.info("=" * 40)
    
    # Load configuration
    config = load_configuration()
    
    # Perform migration
    success = migrate_data(config, log)
    
    if success:
        log.info("Migration completed successfully!")
        log.info("You can now set 'use_api_repository': true in your configuration.json")
        sys.exit(0)
    else:
        log.error("Migration failed!")
        sys.exit(1)


if __name__ == "__main__":
    main() 