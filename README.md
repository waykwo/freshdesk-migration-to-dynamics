# Knowledge Article Migration Tool

A comprehensive Python-based solution for migrating knowledge articles from Freshdesk to Microsoft Dynamics 365 Customer Service. This enterprise-grade tool handles complex migrations including hierarchical category structures, many-to-many relationships, multimedia content, multilingual support, and intelligent internal link resolution.

## 🚀 Key Features

- **Complete Knowledge Base Migration**: Transfers entire knowledge base structure from Freshdesk to Dynamics 365
- **Advanced Category Management**: Maintains parent-child relationships and complex hierarchical category structures
- **Multimedia Support**: Handles image migration with automatic conversion to Dynamics web resources
- **Multilingual Content**: Full support for English and French content with proper language relationships
- **Intelligent Link Resolution**: Automatically updates internal article references to work in Dynamics 365
- **Metadata Preservation**: Maintains article visibility settings, publication status, dates, and author information
- **Robust Error Handling**: Comprehensive logging, retry mechanisms, and automatic token refresh
- **Progress Tracking**: Detailed status reporting and migration progress monitoring
- **Chunked Processing**: Processes articles in configurable batches for optimal performance
- **Environment-Specific Configuration**: Supports multiple deployment environments (Dev, Staging, Production)

## 📋 Prerequisites

### System Requirements

- **Python**: 3.7 or higher
- **Azure Subscription**: With appropriate permissions for Dynamics 365
- **Freshdesk API Access**: Valid API key with knowledge base permissions
- **Microsoft Dynamics 365**: Customer Service environment with knowledge management enabled
- **Azure Key Vault**: For secure credential storage

### Authentication Requirements

- Azure Active Directory application registration
- Refresh tokens for each target environment
- Key Vault access permissions

## 🔧 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/waykwo/knowledge-article-migration.git
cd knowledge-article-migration
```

### 2. Install Required Python Packages

```bash
pip install requests msal azure-identity azure-keyvault-secrets beautifulsoup4 pandas jsonschema icecream
```

### 3. Create Required Directories

```bash
mkdir -p data/images
```

## ⚙️ Configuration

### 1. Environment Variables (`variables.py`)

Create a `variables.py` file with your environment-specific configuration:

```python
# Azure Key Vault Configuration
KEY_VAULT_NAME = "your_keyvault_name"
KEY_VAULT_URI = "https://your_keyvault_name.vault.azure.net/"

# Azure AD Configuration
client_id = "your_client_id"
authority = "https://login.microsoftonline.com/your_tenant_id"
tenant_id = "your_tenant_id"

# Environment-specific refresh tokens
refresh_token_dev = "your_dev_refresh_token"
refresh_token_staging = "your_staging_refresh_token"
refresh_token_prod = "your_prod_refresh_token"

# Environment-specific scopes
scope_dev = ["https://your-dev-org.crm3.dynamics.com/.default"]
scope_staging = ["https://your-staging-org.crm3.dynamics.com/.default"]
scope_prod = ["https://your-prod-org.crm3.dynamics.com/.default"]
```

### 2. API Configuration (`parameters.json`)

Create a `parameters.json` file with your API credentials:

```json
{
  "freshdesk_api": "your_freshdesk_api_key"
}
```

### 3. Azure Key Vault Setup

Store your client secret in Azure Key Vault with the name `cx-consolidation`.

## 📁 Directory Structure

After setup and first run, your directory structure will look like:

```
knowledge-article-migration/
├── data/
│   ├── images/                           # Downloaded and processed images
│   ├── freshdesk_folders_*.csv          # Freshdesk folder structure exports
│   ├── freshdesk_articles_*.json        # Downloaded article content
│   ├── imported_categories_*.json       # Category mapping between systems
│   ├── migrated_articles_*.json         # Migration results and mappings
│   └── internal_article_references.json # Internal link mappings
├── knowledge_article_migration.log      # Comprehensive migration logs
├── parameters.json                      # API configuration
├── variables.py                        # Environment variables
└── knowledge_article_migration.py      # Main migration script
```

## 🚀 Usage

### 1. Run the Migration

```bash
python knowledge_article_migration.py
```

### 2. Environment Selection

When prompted, select your target environment:

- `d` for Development
- `e` for DevPortal
- `s` for Staging
- `p` for Production

### 3. Category Import

When prompted, choose whether to import categories:

- `y` to import new categories from Freshdesk
- `n` to use existing categories in Dynamics

The script will then automatically:

1. Download and process all articles from Freshdesk
2. Migrate articles in configurable chunks
3. Process images and create web resources
4. Update internal article references
5. Handle multilingual content
6. Generate comprehensive reports

## 🔄 Migration Process

### Phase 1: Category Structure Migration

- Retrieves all categories and folders from Freshdesk
- Creates corresponding hierarchical structure in Dynamics 365
- Maintains parent-child relationships and visibility settings
- Maps Freshdesk IDs to Dynamics GUIDs

### Phase 2: Article Content Migration

- Downloads articles from Freshdesk in folder-by-folder batches
- Processes visibility settings (internal vs external)
- Migrates article content, metadata, and publication status
- Associates articles with appropriate categories
- Handles draft vs published status preservation

### Phase 3: Multimedia Processing

- Downloads images from Freshdesk
- Converts and uploads as Dynamics web resources
- Updates article content with new image references
- Maintains image quality and accessibility

### Phase 4: Multilingual Support

- Identifies French translations of articles
- Creates corresponding translations in Dynamics
- Maintains language relationships and metadata
- Supports Canadian French localization

### Phase 5: Internal Link Resolution

- Analyzes all internal article references
- Maps Freshdesk URLs to Dynamics portal URLs
- Updates content with corrected internal links
- Handles links to draft vs published articles

### Phase 6: Finalization

- Updates article numbers for portal integration
- Validates migration completeness
- Generates final migration reports
- Performs cleanup operations

## 🛠️ Advanced Features

### Chunked Processing

The tool processes articles in configurable chunks (default: 50 articles) to:

- Optimize memory usage
- Provide regular progress updates
- Enable recovery from interruptions
- Manage API rate limits effectively

### Automatic Token Refresh

- Detects expired authentication tokens
- Automatically refreshes credentials
- Maintains session continuity
- Handles long-running migrations

### Error Recovery

- Implements retry mechanisms for failed operations
- Provides detailed error logging
- Continues processing after individual failures
- Supports manual intervention points

### Status Preservation

- Maps Freshdesk article status to Dynamics equivalents
- Maintains draft vs published states
- Preserves publication timestamps
- Handles article lifecycle correctly

## 📊 Output Files

### Migration Data Files

- `freshdesk_folders_[timestamp].csv`: Complete folder structure from Freshdesk
- `freshdesk_articles_[timestamp].json`: Downloaded article content with metadata
- `imported_categories_[timestamp]_[env].json`: Category mapping between systems
- `migrated_articles_[env]_[timestamp].json`: Complete migration results with IDs and mappings

### Reference Files

- `internal_article_references_[timestamp].json`: Mapping of internal article links
- `knowledge_article_migration.log`: Comprehensive operation logs with timestamps

### Image Assets

- `data/images/`: All downloaded and processed images with systematic naming

## 🔍 Monitoring and Troubleshooting

### Log Analysis

The migration generates detailed logs including:

- Operation timestamps and durations
- Success/failure status for each article
- Error details and retry attempts
- Performance metrics and statistics

### Common Issues and Solutions

**Authentication Errors**:

- Verify refresh tokens are current
- Check Azure Key Vault permissions
- Ensure client ID and tenant ID are correct

**Rate Limiting**:

- The tool automatically handles Freshdesk and Dynamics API limits
- Implements intelligent backoff strategies
- Provides progress indicators during wait periods

**Memory Management**:

- Uses chunked processing to handle large knowledge bases
- Clears processed data between chunks
- Optimizes image processing workflows

**Incomplete Migrations**:

- Check migration JSON files for partial results
- Run final update functions for missing article numbers
- Use log files to identify and retry failed articles

## 🔧 Customization

### Chunk Size Adjustment

Modify the `chunk_size` parameter in `process_articles_in_chunks()` based on:

- Available system memory
- Network reliability
- Processing performance requirements

### Language Support

Add additional languages by:

- Updating the language detection logic
- Adding language locale mappings
- Modifying translation creation workflows

### Custom Field Mapping

Extend the migration to handle custom fields by:

- Adding field mappings in article data structures
- Updating the migration payload construction
- Implementing validation for custom data types

## 📈 Performance Optimization

### Recommended Settings

- **Chunk Size**: 50 articles (adjust based on memory and network)
- **Retry Attempts**: 3 (balances reliability with speed)
- **Wait Times**: Progressive backoff (5-30 seconds)
- **Token Refresh**: Proactive refresh between chunks

### Monitoring Performance

- Track articles per minute processing rate
- Monitor memory usage during image processing
- Observe API response times and adjust wait periods
- Use log timestamps to identify bottlenecks

## 🔒 Security Considerations

- **Credential Storage**: All sensitive data stored in Azure Key Vault
- **Access Control**: Environment-specific permissions and tokens
- **Logging**: No sensitive data written to log files
- **Encryption**: All API communications use HTTPS/TLS

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

For support and questions:

- Check the comprehensive logs in `knowledge_article_migration.log`
- Review the migration data files for status information
- Refer to the troubleshooting section above
- Open an issue in the GitHub repository

## 🏆 Key Design Principles

- Built for enterprise-scale knowledge base migrations
- Designed with reliability and maintainability in mind
- Optimized for Freshdesk to Dynamics 365 workflows
- Supports complex organizational knowledge management needs
