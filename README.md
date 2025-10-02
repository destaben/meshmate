# MeshMate

Meshtastic message listener and ping responder bot.

## Features

- Listens to text messages on configured channels
- Automatically responds to `/ping` commands with hop and signal info
- **RED weather alerts** via `/meteo` command using AEMET API (Spain)
- **Prometheus metrics** endpoint for monitoring and observability
- **HTTP API** for sending messages programmatically
- Scheduled commands and reminders with flexible timing
- Modular handler system for extensible commands
- Configurable channel monitoring
- JSON structured logging
- Dockerized for easy deployment

## Usage

### Local Python

```bash
# Install dependencies
pip install -r requirements.txt

# Run with ping only
python main.py --ip 192.168.1.230

# Run with RED weather alerts (requires AEMET API key)
python main.py --ip 192.168.1.230 --aemet-api-key YOUR_API_KEY

# Monitor specific channels with weather alerts
python main.py --ip 192.168.1.230 --channels iberia madrid --aemet-api-key YOUR_API_KEY

# Monitor all channels with full logging
python main.py --ip 192.168.1.230 --channels all --aemet-api-key YOUR_API_KEY --log-all-messages
```

### Docker

#### Pre-built Images (Recommended)

```bash
# Pull from GitHub Container Registry (automatic builds)
docker pull ghcr.io/destaben/meshmate:latest

# Run with ping only
docker run -d --name meshmate-container ghcr.io/destaben/meshmate:latest \
    --ip 192.168.1.230

# Run with RED weather alerts and persistent storage
docker run -d --name meshmate-container \
    -v $(pwd)/data:/app/data \
    ghcr.io/destaben/meshmate:latest \
    --ip 192.168.1.230 --aemet-api-key YOUR_API_KEY

# Run with custom channels, weather alerts, and logs
docker run -d --name meshmate-container \
    -v $(pwd)/data:/app/data \
    -v $(pwd)/logs:/app/logs \
    ghcr.io/destaben/meshmate:latest \
    --ip 192.168.1.230 --channels iberia madrid --aemet-api-key YOUR_API_KEY

# View logs
docker logs -f meshmate-container

# Stop the container
docker stop meshmate-container
docker rm meshmate-container
```

#### Docker Compose (Recommended for Production)

```bash
# Copy environment configuration
cp .env.example .env
# Edit .env with your configuration

# Start with docker-compose (includes persistent volumes)
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

#### Manual Build

```bash
# Build the image locally
docker build -t meshmate .

# Run locally built image
docker run -d --name meshmate-container meshmate --ip 192.168.1.230
```

## Configuration

### Environment Variables

When using Docker or docker-compose:

- **Required**:
  - `MESHTASTIC_IP` or `MESHTASTIC_HOSTNAME`: IP address or hostname of the Meshtastic device

- **Optional**:
  - `CHANNELS`: List of channels to monitor (default: `iberia`). Use `all` for all channels
  - `LOG_ALL_MESSAGES`: Log all messages, not just commands (default: `false`)
  - `AEMET_API_KEY`: AEMET API key for RED weather alerts (`/meteo` command)
  - `API_PORT`: HTTP API server port (default: `9900`)
  - `API_HOST`: HTTP API server host (default: `0.0.0.0`)

### Command Line Arguments (Local Python)

- `--ip` or `--hostname`: IP address or hostname of the Meshtastic device
- `--channels`: List of channels to monitor (default: iberia). Use "all" for all channels
- `--log-all-messages`: Log all messages, not just commands  
- `--aemet-api-key`: AEMET API key for RED weather alerts (/meteo command)

## Architecture

MeshMate uses a modular handler system where each command is implemented as a separate handler:

- **PingHandler** (`handlers/ping_handler.py`): Handles `/ping` commands
- **MeteoHandler** (`handlers/meteo_handler.py`): Handles `/meteo` weather alerts
- **ScheduleHandler** (`handlers/schedule_handler.py`): Handles `/schedule` automated commands
- **InfoHandler** (`handlers/info_handler.py`): Handles `/meshmate` project information
- **HelpHandler** (`handlers/help_handler.py`): Handles `/?` help command
- **BaseHandler** (`handlers/base_handler.py`): Common functionality for all handlers

## Scheduler System

The scheduler system allows users to automate commands and reminders with flexible timing:

- **ScheduleManager** (`schedule_manager.py`): Manages scheduled tasks with JSON persistence
- **One-time Schedules**: Execute once at specified time, then auto-delete
- **Recurring Schedules**: Execute repeatedly on specified weekdays (Spanish names)
- **Background Worker**: Runs in a separate thread checking for due schedules every minute
- **User Limits**: Maximum 5 schedules per user to prevent abuse
- **Persistence**: Schedules survive bot restarts through JSON file storage

## Connection Resilience

MeshMate includes multiple layers of connection resilience:

### Auto-Reconnection System

- **Health Monitoring**: Connection health checks every 30 seconds
- **Aggressive Cleanup**: Complete interface cleanup on connection loss
- **Thread Safety**: Safe message sending with connection validation
- **Background Recovery**: Automatic reconnection with exponential backoff

### Error Handling

- **BrokenPipe Suppression**: Silences harmless Meshtastic heartbeat errors
- **Connection Validation**: Multi-layer connection health testing
- **Graceful Degradation**: Schedules and commands skip when connection is down
- **Process Restart**: Automatic process restart after 10 consecutive failures

### Docker Integration

- **Health Checks**: Container health monitoring with automatic restart
- **Persistent Data**: Volumes ensure schedules survive container restarts
- **Resource Limits**: Prevents resource exhaustion during reconnection storms
- **Restart Policies**: Automatic container restart on failure

## Commands

### `/ping`

Responds with technical information:

```text
@username pong (via radio/MQTT) - hops_used/hop_limit hops (SNR: XdB, RSSI: XdBm)
```

### `/meteo` (requires AEMET API key)

Shows **RED (extreme) weather alerts only** for Spain. Sends separate cards for each alert type:

```text
🔴 ALERTA ROJA TORMENTAS:
Valencia, Alicante, Castellón
📡 AEMET

🔴 ALERTA ROJA LLUVIA:
Madrid, Barcelona, Sevilla +3
📡 AEMET
```

**Features:**

- Only shows RED/extreme level alerts (most critical)
- One card per weather phenomenon (full names: Tormentas, Lluvia, Viento, etc.)
- Shows all affected provinces (up to 200 character limit)
- Clean province names (removes "Provincia de", "Litoral de", etc.)
- Automatic splitting if multiple alert types exist

### `/meshmate`

Shows project information and encourages contributions:

```text
🤖 MeshMate Bot

✨ Ping, avisos meteo, info
🔗 github.com/destaben/meshmate

¡Contribuye! 🚀
```

## HTTP API & Prometheus Metrics

MeshMate includes an HTTP API server for programmatic control and Prometheus metrics for monitoring.

### Endpoints

#### `GET /metrics`

Prometheus-compatible metrics endpoint for scraping. Returns metrics in Prometheus text format.

**Available Metrics:**

- `meshmate_messages_received_total` - Total messages received (by channel, sender)
- `meshmate_messages_sent_total` - Total messages sent (by channel)
- `meshmate_commands_processed_total` - Commands successfully processed (by command, channel)
- `meshmate_commands_failed_total` - Failed commands (by command, channel)
- `meshmate_command_duration_seconds` - Command processing time histogram (by command)
- `meshmate_meshtastic_connection_status` - Connection status (1=connected, 0=disconnected)
- `meshmate_signal_rssi` - Last received signal RSSI (by sender, channel)
- `meshmate_signal_snr` - Last received signal SNR (by sender, channel)
- `meshmate_hops_used` - Hops used in last message (by sender, channel)
- `meshmate_scheduled_tasks_total` - Active scheduled tasks (by user)
- `meshmate_scheduled_tasks_executed_total` - Executed scheduled tasks (by user)
- `meshmate_errors_total` - Total errors (by error_type)
- `meshmate_http_requests_total` - HTTP API requests (by endpoint, method, status)

**Example:**

```bash
curl http://localhost:9900/metrics
```

#### `GET /health`

Health check endpoint for monitoring system status.

**Response:**

```json
{
  "status": "healthy",
  "meshtastic_connected": true,
  "version": "1.0.0"
}
```

#### `POST /send`

Send a message to Meshtastic network via HTTP.

**Request Body:**

```json
{
  "text": "Hello from HTTP API!",
  "channel": 0
}
```

**Parameters:**

- `text` (required): Message text to send
- `channel` (optional): Channel index (default: 0)

**Success Response (200):**

```json
{
  "success": true,
  "message": "Message sent successfully",
  "channel": 0
}
```

**Error Responses:**

- `400` - Invalid request (missing text, invalid channel)
- `503` - Meshtastic interface not available
- `500` - Internal server error

**Example:**

```bash
# Send a message to default channel (0)
curl -X POST http://localhost:9900/send \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello Mesh Network!"}'

# Send to specific channel
curl -X POST http://localhost:9900/send \
  -H "Content-Type: application/json" \
  -d '{"text": "Alert: System status OK", "channel": 1}'
```

#### `GET /info`

Get bot information and available endpoints.

**Response:**

```json
{
  "name": "MeshMate",
  "version": "1.0.0",
  "endpoints": {
    "/metrics": "Prometheus metrics (GET)",
    "/health": "Health check (GET)",
    "/send": "Send message (POST)",
    "/info": "Bot information (GET)"
  }
}
```

### Prometheus Configuration

Add this to your `prometheus.yml` to scrape MeshMate metrics:

```yaml
scrape_configs:
  - job_name: 'meshmate'
    static_configs:
      - targets: ['localhost:9900']  # Adjust hostname as needed
    scrape_interval: 15s
    scrape_timeout: 10s
```

**Docker Network Example:**

If running both Prometheus and MeshMate in Docker:

```yaml
scrape_configs:
  - job_name: 'meshmate'
    static_configs:
      - targets: ['host.docker.internal:9900']  # Access host network
```

### API Server Configuration

The API server can be configured via environment variables:

```bash
# Default configuration
API_PORT=9900
API_HOST=0.0.0.0

# Custom port
API_PORT=9090

# Bind to localhost only (more secure)
API_HOST=127.0.0.1
```

### Security Considerations

- The API server does not include authentication by default
- For production use, consider:
  - Running behind a reverse proxy (nginx, traefik) with authentication
  - Using firewall rules to restrict access
  - Binding to `127.0.0.1` for local-only access
  - Implementing rate limiting at the proxy level

### `/schedule`

Schedule automated commands and reminders:

```text
📅 Schedule

• add HH:MM texto [días]
• list
• del ID

Ej: add 09:30 /ping all
```

**Features:**

- Up to 5 schedules per user
- Support for commands (`/ping`, `/meteo`, etc.) and text messages
- **One-time execution** by default (runs once then auto-deletes)
- **Recurring schedules** with Spanish weekdays (lunes, martes, miercoles, jueves, viernes, sabado, domingo)
- Persistence across bot restarts
- Individual user management

**Usage Examples:**

- `/schedule add 08:00 /meteo` - Check weather alerts once at 8 AM
- `/schedule add 14:00 Lunch break lunes,miercoles,viernes` - Recurring lunch reminder
- `/schedule add 09:30 /ping sabado,domingo` - Weekend connectivity tests
- `/schedule add 07:00 Good morning all` - Daily morning message
- `/schedule list` - View your active schedules
- `/schedule del 2` - Delete schedule #2

**Weekday Format:**

- Use Spanish weekday names separated by commas: `lunes,martes,miercoles,jueves,viernes,sabado,domingo`
- Use `all` for every day of the week

### `/?`

Displays available commands:

```text
📋 Comandos disponibles:

/ping - Test de conectividad
/meteo - Avisos rojos AEMET
/schedule - Programar comandos
/meshmate - Info del proyecto
/? - Esta ayuda

🤖 MeshMate Bot
```

## Requirements

- Python 3.11+
- Meshtastic device with TCP interface enabled
- Network connectivity to the Meshtastic device
- AEMET API key (optional, for weather warnings)

## Getting AEMET API Key

1. Register at [AEMET OpenData](https://opendata.aemet.es/centrodedescargas/obtencionAPIKey)
2. Verify your email
3. Use the provided API key with `--aemet-api-key` parameter

## Data Persistence

MeshMate stores user data in persistent files:

- **`data/schedules.json`** - User scheduled commands and reminders
- **`logs/`** - Application logs (optional, for debugging)

### Docker Volumes

When running with Docker, mount volumes to persist data between container restarts:

```bash
# Minimal persistence (schedules only)
-v $(pwd)/data:/app/data

# Full persistence (schedules + logs)
-v $(pwd)/data:/app/data -v $(pwd)/logs:/app/logs
```

The `docker-compose.yml` file includes these volumes automatically.

## Project Structure

```text
meshmate/
├── main.py                 # Main application entry point
├── schedule_manager.py     # Schedule management and persistence
├── handlers/               # Modular command handlers
│   ├── base_handler.py     # Base class for all handlers
│   ├── ping_handler.py     # Ping command implementation
│   ├── meteo_handler.py    # Weather alerts implementation
│   ├── schedule_handler.py # Schedule management commands
│   ├── info_handler.py     # Project information
│   └── help_handler.py     # Help command
├── data/                   # Persistent data directory
│   └── schedules.json      # Scheduled tasks with weekday support (auto-created)
├── logs/                   # Application logs (optional)
├── requirements.txt        # Python dependencies
├── Dockerfile             # Docker container configuration
├── docker-compose.yml     # Production deployment configuration
└── README.md              # This file
```

## Automated Builds

MeshMate includes GitHub Actions for automated building and deployment:

- **Tests**: Run on every push/PR to ensure code quality
- **Docker Images**: Automatically built and pushed on main branch updates
- **Multi-platform**: Supports both AMD64 and ARM64 architectures
- **Container Registry**: Images available on GitHub Container Registry

### Available Images

| Registry | Image | Updates |
|----------|--------|---------|
| GitHub Container Registry | `ghcr.io/destaben/meshmate:latest` | Every main branch push |

## Contributing

To add new commands:

1. Create a new handler in `handlers/` inheriting from `BaseHandler`
2. Implement the `can_handle()` and `handle()` methods
3. Register your handler in `main.py`

Example handler structure:

```python
from .base_handler import BaseHandler

class MyHandler(BaseHandler):
    def __init__(self, channel=None):
        super().__init__(command='mycommand', channel=channel)
    
    def handle(self, packet, interface, log_json):
        # Your command logic here
        pass
```
