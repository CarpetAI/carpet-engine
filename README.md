# Session Events API

A FastAPI application for retrieving session events from Firebase storage.

## Features

- Retrieve session events by session ID
- Firebase Cloud Storage integration
- RESTful API with automatic documentation
- Health check endpoints
- Comprehensive logging

## Project Structure

```
carpet-engine/
├── app/
│   ├── __init__.py
│   ├── main.py              # Main FastAPI application
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py      # Application settings
│   ├── routers/
│   │   ├── __init__.py
│   │   └── sessions.py      # Session-related endpoints
│   └── services/
│       ├── __init__.py
│       └── firebase_service.py  # Firebase operations
├── main.py                  # Alternative entry point
├── requirements.txt         # Python dependencies
├── env.example             # Environment variables template
└── README.md               # This file
```

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**
   ```bash
   cp env.example .env
   # Edit .env with your Firebase configuration
   ```

3. **Set up Firebase:**
   - Download your Firebase service account key JSON file
   - Place it in a secure location (NOT in the repository)
   - Update the `SERVICE_ACCOUNT_KEY_PATH` in your `.env` file to point to the key file
   - Ensure your Firebase project has Cloud Storage enabled

## Security Considerations

⚠️ **IMPORTANT:** Before running this application:

1. **Never commit service account keys** - The `serviceAccountKey.json` file is excluded from version control
2. **Use environment variables** - All sensitive configuration should be set via environment variables
3. **Secure your Firebase project** - Ensure proper IAM permissions are configured
4. **Review API keys** - If using optional features (Pinecone, OpenAI), ensure API keys are properly secured

## Running the Application

### Development
```bash
# Using the main app structure (recommended)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or using the alternative entry point
python main.py
```

### Production
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API Endpoints

### Base URL
- `GET /` - Root endpoint
- `GET /health` - Health check

### Session Events
- `GET /api/sessions/{session_id}/events` - Get events for a specific session

### Example Usage

```bash
# Get events for session "abc123"
curl http://localhost:8000/api/sessions/abc123/events
```

## API Documentation

Once the server is running, you can access:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Configuration

The application uses environment variables for configuration. See `env.example` for available options.

### Required Firebase Configuration
- `SERVICE_ACCOUNT_KEY_PATH`: Path to your Firebase service account JSON file
- `BUCKET_NAME`: Firebase Cloud Storage bucket name (default: "session-replays")

### Optional External Services
- `PINECONE_API_KEY`: Pinecone API key for RAG features
- `OPENAI_API_KEY`: OpenAI API key for AI features

## Development

### Adding New Endpoints

1. Create new router files in `app/routers/`
2. Add business logic in `app/services/`
3. Include the router in `app/main.py`

### Project Structure Best Practices

- **Routers**: Handle HTTP requests and responses
- **Services**: Contain business logic and external service interactions
- **Config**: Application settings and environment variables
- **Models**: Data models and schemas (add as needed)

## Error Handling

The API includes comprehensive error handling:
- Invalid session IDs return empty arrays
- Firebase errors are logged and handled gracefully
- HTTP 500 errors for unexpected exceptions

## Logging

The application uses Python's built-in logging module. Logs include:
- Session retrieval attempts
- Error details
- Event count information
- Firebase operation status

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

[Add your license here] 