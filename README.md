# MeshMate

Meshtastic message listener and ping responder bot.

## Features

- Listens to all Meshtastic text messages
- Automatically responds to `/ping` commands in the "iberia" channel
- Provides detailed hop and signal information in responses
- Dockerized for easy deployment

## Usage

### Local Python

```bash
# Install dependencies
pip install -r requirements.txt

# Run the script
python main.py --ip 192.168.1.230
```

### Docker

#### Docker Commands

```bash
# Build the image
docker build -t meshmate .

# Run the container
docker run -d --name meshmate-container --restart unless-stopped meshmate --ip 192.168.1.230

# View logs
docker logs -f meshmate-container

# Stop the container
docker stop meshmate-container
docker rm meshmate-container
```

## Configuration

The script requires a Meshtastic device IP address to be specified:

- `--ip` or `--hostname`: IP address or hostname of the Meshtastic device (required)

## Ping Response

When someone sends `/ping` in the "iberia" channel, the bot responds with:

```text
@username pong (via radio/MQTT) - hops_used/hop_limit hops (SNR: XdB, RSSI: XdBm)
```

## Requirements

- Python 3.11+
- Meshtastic device with TCP interface enabled
- Network connectivity to the Meshtastic device