# Knowledge Article Migration Tool

A robust Python-based tool for migrating knowledge articles from Freshdesk to Microsoft Dynamics 365 Customer Service. This tool handles complex migrations including the many-to-many relationship between knowledgearticles and categories, images, and multilingual content (English and French).

## Features

- Migrates complete knowledge base structure from Freshdesk to Dynamics 365
- Preserves category hierarchies and article relationships
- Handles image migration with automatic conversion to Dynamics web resources
- Supports multilingual content (English and French)
- Maintains article metadata including visibility settings and publication dates
- Provides comprehensive logging for tracking migration progress
- Includes error handling and detailed status reporting

## Prerequisites

- Python 3.7 or higher
- Azure subscription with appropriate permissions
- Freshdesk API key
- Microsoft Dynamics 365 environment
- Azure Key Vault access

## Required Python Packages

- requests
- msal
- azure-identity
- azure-keyvault-secrets
- beautifulsoup4

```bash
pip install requests msal azure-identity azure-keyvault-secrets beautifulsoup4
```

## Configuration

1. Set up Dataverse variables in `variables.py`:
```python
KEY_VAULT_NAME = "your_keyvault_name"
KEY_VAULT_URI = "your_keyvault_uri"
client_id = "your_client_id"
authority = "your_authority_url"
scope = ["your_scope"]
```

2 Ensure you have appropriate Azure Key Vault access configured with the secret replacing "SECRET_NAME".

## Directory Structure

```
├── data/
│   ├── images/
│   ├── freshdesk_folders_*.csv
│   ├── freshdesk_articles_*.json
│   ├── imported_categories_*.json
│   └── migrated_articles_*.json
├── knowledge_article_migration.log
├── parameters.json
├── variables.py
└── knowledge_article_migration.py
```

## Usage

1. Configure your credentials and parameters as described in the Configuration section

2. Run the migration script:
```bash
python knowledge_article_migration.py
```

3. Monitor the migration progress in `knowledge_article_migration.log`

## Migration Process

1. **Category Structure Migration**
   - Retrieves all categories and folders from Freshdesk
   - Creates corresponding category structure in Dynamics 365
   - Maintains parent-child relationships

2. **Article Migration**
   - Processes articles folder by folder
   - Handles visibility settings (internal/external)
   - Migrates article content and metadata
   - Associates articles with appropriate categories

3. **Image Processing**
   - Downloads images from Freshdesk
   - Converts and uploads as Dynamics web resources
   - Updates article content with new image references

4. **Multilingual Support**
   - Identifies French translations of articles
   - Creates corresponding translations in Dynamics
   - Maintains language relationships and metadata

## Error Handling

The script includes comprehensive error handling and logging:
- Failed operations are logged with detailed error messages
- Migration continues even if individual articles fail
- Separate logs for categories, articles, and images
- Timestamps for all operations

## Output Files

- `freshdesk_folders_[timestamp].csv`: List of all Freshdesk folders and their metadata
- `freshdesk_articles_[timestamp].json`: Downloaded article content from Freshdesk
- `imported_categories_[timestamp]_[env]_env.json`: Category mapping between systems
- `migrated_articles_[timestamp].json`: Successfully migrated articles with their new IDs

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
