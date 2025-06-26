# Migration Guide

This guide explains how to migrate your Home Key data from the file-based repository to the API-based repository.

## Prerequisites

1. Ensure your API server is running and accessible
2. Make sure the `api_base_url` is correctly configured in `configuration.json`
3. The API server must support the required endpoints:
   - `POST /_r/read_homekey_data`
   - `POST /_r/store_homekey_data`

## Running the Migration

### Step 1: Run the Migration Script

```bash
python migration.py
```

The script will:
- Read your current `configuration.json` to get file paths and API URL
- Load all data from your existing file-based repository
- Transfer all data to the API repository
- Verify the migration was successful
- Provide detailed logging of the process

### Step 2: Update Configuration

After a successful migration, update your `configuration.json` to use the API repository:

```json
{
    "homekey": {
        "persist": "homekey.json",
        "use_api_repository": true,
        "api_base_url": "https://your-api-server.com",
        "api_secret": "your-secret-key-here"
    }
}
```

## Migration Output

The migration script provides detailed logging:

```
[2024-01-15 10:30:00] [    INFO] Home Key Repository Migration Tool
[2024-01-15 10:30:00] [    INFO] ========================================
[2024-01-15 10:30:00] [    INFO] Starting migration from homekey.json to https://api.example.com
[2024-01-15 10:30:00] [    INFO] Loading data from file-based repository...
[2024-01-15 10:30:00] [    INFO] Connecting to API repository...
[2024-01-15 10:30:00] [    INFO] Found 2 issuers in file repository
[2024-01-15 10:30:00] [    INFO] Reader private key: 1a2b3c4d5e6f7890...
[2024-01-15 10:30:00] [    INFO] Reader identifier: 9876543210abcdef
[2024-01-15 10:30:00] [    INFO] Migrating reader configuration...
[2024-01-15 10:30:01] [    INFO] Migrating issuers...
[2024-01-15 10:30:01] [    INFO] Migrated issuer 1a2b3c4d5e6f7890... with 3 endpoints
[2024-01-15 10:30:01] [    INFO] Migrated issuer 9876543210abcdef... with 1 endpoints
[2024-01-15 10:30:01] [    INFO] Migration completed successfully!
[2024-01-15 10:30:01] [    INFO] Verifying migration...
[2024-01-15 10:30:02] [    INFO] ✓ Migration verification successful!
[2024-01-15 10:30:02] [    INFO] Migration completed successfully!
[2024-01-15 10:30:02] [    INFO] You can now set 'use_api_repository': true in your configuration.json
```

## What Gets Migrated

The migration transfers:
- **Reader Private Key**: The device's private cryptographic key
- **Reader Identifier**: The unique device identifier
- **All Issuers**: Organizations that can issue Home Keys
- **All Endpoints**: Individual Home Key devices/cards for each issuer

## Error Handling

### Common Issues

1. **Configuration file not found**
   ```
   Configuration file configuration.json not found
   ```
   - Ensure you're running the script from the correct directory
   - Check that `configuration.json` exists

2. **No API URL configured**
   ```
   No api_base_url found in configuration
   ```
   - Add `api_base_url` to your `homekey` configuration section

3. **File doesn't exist**
   ```
   File homekey.json does not exist. Nothing to migrate.
   ```
   - This is normal if you haven't used the system yet
   - The migration will complete successfully with no data

4. **API connection failed**
   ```
   Migration failed: ConnectionError...
   ```
   - Check that your API server is running
   - Verify the `api_base_url` is correct
   - Ensure network connectivity

5. **Verification failed**
   ```
   Migration verification failed!
   ```
   - The data didn't transfer correctly
   - Check API server logs for errors
   - Try running the migration again

## Safety

- The migration script **does not delete** your original file
- The original `homekey.json` file remains untouched
- You can safely run the migration multiple times
- If migration fails, your original data is preserved

## After Migration

Once migration is complete and you've updated your configuration:

1. Restart your Home Key reader application
2. The system will now use the API repository
3. Data will sync automatically every minute
4. Changes will be saved to the API immediately

## Rollback

To rollback to file-based storage:

1. Set `use_api_repository`: `false` in `configuration.json`
2. Restart the application
3. Your original file data will be used again 