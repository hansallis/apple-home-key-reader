# API Repository

The `APIRepository` class is an alternative to the file-based `Repository` class that stores and retrieves Home Key data from a JSON API endpoint instead of a local file.

## Features

- **Automatic Sync**: Reads data from the API every 60 seconds to stay synchronized
- **Immediate Updates**: Writes changes to the API immediately when data is modified
- **Error Handling**: Gracefully handles network errors with proper logging
- **Thread Safety**: Uses locks to ensure safe concurrent access
- **Drop-in Replacement**: Inherits from `Repository` so it's fully compatible

## Configuration

To use the API repository, set `use_api_repository` to `true` in your `configuration.json`:

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

## Authentication

The API repository supports Bearer token authentication. If you configure an `api_secret` in your configuration file, it will be sent as an `Authorization: Bearer <secret>` header with all API requests.

## API Endpoints

The repository expects the following HTTP endpoints (both must be POST requests):

### POST /_r/read_homekey_data
Reads the current Home Key configuration. Send an empty JSON object `{}` as the request body.

Returns the current configuration as JSON:

```json
{
    "reader_private_key": "hex_encoded_key",
    "reader_identifier": "hex_encoded_id",
    "issuers": {
        "issuer_id_hex": {
            "id": "hex_encoded_id",
            "public_key": "hex_encoded_key",
            "endpoints": [...]
        }
    }
}
```

### POST /_r/store_homekey_data
Stores/updates the Home Key configuration. Accepts the same JSON structure as returned by the read endpoint.

## Usage

The API repository is a drop-in replacement for the file-based repository:

```python
from api_repository import APIRepository

# Create an API repository without authentication
repo = APIRepository("https://your-api-server.com")

# Create an API repository with authentication
repo = APIRepository("https://your-api-server.com", "your-secret-key")

# Use it exactly like the regular Repository
issuers = repo.get_all_issuers()
repo.upsert_issuer(new_issuer)
```

## Error Handling

- Network timeouts and connection errors are logged as warnings
- Invalid JSON responses are logged as errors
- The application continues to function with cached data if the API is temporarily unavailable
- On startup, if the API is unavailable, the repository starts with default empty state

## Background Sync

A background daemon thread automatically reads from the API every 60 seconds to keep the local state synchronized with the server. This ensures that changes made by other clients are reflected locally.

The background thread is automatically stopped when the repository object is destroyed. 