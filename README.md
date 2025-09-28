# MeshMate

Meshtastic message listener and ping responder bot.

## Features

- Listens t```text
🔴 ALERTA ROJA TORMENTAS:
Valencia, Alicante, Castellón
📡 AEMET

🔴 ALERTA ROJA LLUVIA:
Madrid, Barcelona, Sevilla +3
📡 AEMET
```c text messages on configured channels
- Automatically responds to `/ping` commands with hop and signal info
- **RED weather alerts** via `/meteo` command using AEMET API (Spain)
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

#### Docker Commands

```bash
# Build the image
docker build -t meshmate .

# Run with ping only
docker run -d --name meshmate-container meshmate --ip 192.168.1.230

# Run with RED weather alerts
docker run -d --name meshmate-container meshmate \
    --ip 192.168.1.230 --aemet-api-key YOUR_API_KEY

# Run with custom channels and weather alerts
docker run -d --name meshmate-container meshmate \
    --ip 192.168.1.230 --channels iberia madrid --aemet-api-key YOUR_API_KEY

# View logs
docker logs -f meshmate-container

# Stop the container
docker stop meshmate-container
docker rm meshmate-container
```

## Configuration

### Required Parameters
- `--ip` or `--hostname`: IP address or hostname of the Meshtastic device

### Optional Parameters

- `--channels`: List of channels to monitor (default: iberia). Use "all" for all channels
- `--log-all-messages`: Log all messages, not just commands  
- `--aemet-api-key`: AEMET API key for RED weather alerts (/meteo command)

## Architecture

MeshMate uses a modular handler system where each command is implemented as a separate handler:

- **PingHandler** (`handlers/ping_handler.py`): Handles `/ping` commands
- **MeteoHandler** (`handlers/meteo_handler.py`): Handles `/meteo` weather alerts
- **BaseHandler** (`handlers/base_handler.py`): Common functionality for all handlers

## Commands

### `/ping`

Responds with technical information:

```text
@username pong (via radio/MQTT) - hops_used/hop_limit hops (SNR: XdB, RSSI: XdBm)
```

### `/meteo` (requires AEMET API key)

Shows **RED (extreme) weather alerts only** for Spain. Sends separate cards for each alert type:

```text
@username

🔴 ALERTA ROJA TORM:
Valencia, Alicante, Castellón
📡 AEMET

� ALERTA ROJA LLUV:
Madrid, Barcelona, Sevilla +3
📡 AEMET
```

**Features:**

- Only shows RED/extreme level alerts (most critical)
- One card per weather phenomenon (full names: Tormentas, Lluvia, Viento, etc.)
- Shows all affected provinces (up to 200 character limit)
- Clean province names (removes "Provincia de", "Litoral de", etc.)
- Automatic splitting if multiple alert types exist

## Requirements

- Python 3.11+
- Meshtastic device with TCP interface enabled
- Network connectivity to the Meshtastic device
- AEMET API key (optional, for weather warnings)

## Getting AEMET API Key

1. Register at [AEMET OpenData](https://opendata.aemet.es/centrodedescargas/obtencionAPIKey)
2. Verify your email
3. Use the provided API key with `--aemet-api-key` parameter

## Project Structure

```text
meshmate/
├── main.py              # Main application entry point
├── handlers/            # Modular command handlers
│   ├── base_handler.py  # Base class for all handlers
│   ├── ping_handler.py  # Ping command implementation
│   └── meteo_handler.py # Weather alerts implementation
├── requirements.txt     # Python dependencies
├── Dockerfile          # Docker container configuration
└── README.md           # This file
```

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