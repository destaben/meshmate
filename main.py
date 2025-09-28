import time
import meshtastic
import meshtastic.tcp_interface
from pubsub import pub
from datetime import datetime
import argparse
import json
import logging

# Configure JSON logging
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": "meshmate",
            "message": record.getMessage(),
        }
        
        # Add extra fields if they exist
        if hasattr(record, 'extra'):
            log_entry.update(record.extra)
            
        return json.dumps(log_entry, ensure_ascii=False)

# Setup root logger to suppress all non-JSON logs
logging.getLogger().handlers.clear()  # Remove all existing handlers
logging.getLogger().setLevel(logging.CRITICAL)  # Block everything at root level

# Setup our specific logger
logger = logging.getLogger('meshmate')
logger.setLevel(logging.INFO)
logger.propagate = False  # Don't propagate to root logger

# Create console handler with JSON formatter
console_handler = logging.StreamHandler()
console_handler.setFormatter(JSONFormatter())
logger.addHandler(console_handler)

# Disable all other loggers completely
logging.getLogger("meshtastic").setLevel(logging.CRITICAL)
logging.getLogger("meshtastic").propagate = False
for name in logging.Logger.manager.loggerDict:
    if name != 'meshmate':
        logging.getLogger(name).setLevel(logging.CRITICAL)
        logging.getLogger(name).propagate = False

def log_json(level, message, **extra_fields):
    """Helper function to log with extra fields"""
    record = logger.makeRecord(
        logger.name, getattr(logging, level.upper()), 
        "", 0, message, (), None
    )
    record.extra = extra_fields
    logger.handle(record)

def onReceive(packet, interface):
    # Only process text messages
    if 'decoded' in packet and 'portnum' in packet['decoded']:
        if packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
            # Extract message information
            sender_id = packet.get('fromId', 'Unknown')
            message_text = packet['decoded'].get('text', '')
            rx_time = packet.get('rxTime', 0)
            channel = packet.get('channel', 0)
            
            # Get channel name if available from interface
            channel_name = f"Channel {channel}"
            try:
                if hasattr(interface, 'localNode') and interface.localNode:
                    channels = interface.localNode.channels
                    if channel < len(channels) and channels[channel]:
                        settings = channels[channel].settings
                        if hasattr(settings, 'name') and settings.name:
                            channel_name = settings.name
            except:
                pass  # Fallback to default channel name
            
            # Convert timestamp to readable date
            if rx_time:
                timestamp = datetime.fromtimestamp(rx_time).strftime('%H:%M:%S %d/%m/%Y')
            else:
                timestamp = 'No timestamp'
            
            # Log message in JSON format
            log_json("info", "Message received", 
                event_type="message_received",
                sender_id=sender_id,
                message_text=message_text,
                channel=channel,
                channel_name=channel_name,
                timestamp=timestamp,
                rx_time=rx_time,
                hop_limit=packet.get('hopLimit'),
                hop_start=packet.get('hopStart'),
                via_mqtt=packet.get('viaMqtt', False),
                rx_snr=packet.get('rxSnr'),
                rx_rssi=packet.get('rxRssi'),
                message_id=packet.get('id')
            )
            
            # Check for /ping command in iberia channel
            if channel_name.lower() == 'iberia' and message_text.strip().lower() == '/ping':
                try:
                    # Extract hop information
                    hop_limit = packet.get('hopLimit', 0)
                    hop_start = packet.get('hopStart', 0)
                    via_mqtt = packet.get('viaMqtt', False)
                    rx_snr = packet.get('rxSnr', None)
                    rx_rssi = packet.get('rxRssi', None)
                    message_id = packet.get('id', None)
                    
                    # Calculate hops used (hopStart - hopLimit)
                    hops_used = hop_start - hop_limit if hop_start > 0 else 0
                    
                    # Build response message
                    response = "pong"
                    
                    # Add reception method
                    if via_mqtt:
                        response += " (via MQTT)"
                    else:
                        response += " (via radio)"
                    
                    # Add hop information
                    if hop_start > 0:
                        response += f" - {hops_used}/{hop_start} hops"
                    
                    # Add signal info if available
                    signal_info = []
                    if rx_snr is not None:
                        signal_info.append(f"SNR: {rx_snr}dB")
                    if rx_rssi is not None:
                        signal_info.append(f"RSSI: {rx_rssi}dBm")
                    
                    if signal_info:
                        response += f" ({', '.join(signal_info)})"
                    
                    # Add user mention to make it clear it's a response
                    node_name = sender_id.replace('!', '') if sender_id.startswith('!') else sender_id
                    final_response = f"@{node_name} {response}"
                    
                    interface.sendText(final_response, channelIndex=channel)
                    
                    log_json("info", "Ping response sent",
                        event_type="ping_response_sent",
                        response_text=final_response,
                        original_message_id=message_id,
                        sender_id=sender_id,
                        channel_name=channel_name,
                        channel=channel,
                        hops_used=hops_used,
                        hop_start=hop_start,
                        hop_limit=hop_limit,
                        via_mqtt=via_mqtt,
                        rx_snr=rx_snr,
                        rx_rssi=rx_rssi
                    )
                        
                except Exception as e:
                    log_json("error", "Error sending ping reply",
                        event_type="ping_response_error",
                        error=str(e),
                        sender_id=sender_id,
                        channel_name=channel_name,
                        original_message_id=message_id
                    )

def onConnection(interface, topic=pub.AUTO_TOPIC):
    log_json("info", "Connected to Meshtastic network",
        event_type="connection_established",
        status="connected"
    )

# Subscribe to events
pub.subscribe(onReceive, "meshtastic.receive")
pub.subscribe(onConnection, "meshtastic.connection.established")

# Parse command line arguments
parser = argparse.ArgumentParser(description='Meshtastic message listener and ping responder')
parser.add_argument('--ip', '--hostname', required=True,
                    help='IP address or hostname of the Meshtastic device (required)')
args = parser.parse_args()

log_json("info", "Starting Meshtastic connection",
    event_type="startup",
    target_host=args.ip
)

try:
    interface = meshtastic.tcp_interface.TCPInterface(hostname=args.ip)
    log_json("info", "TCP interface created successfully",
        event_type="interface_created",
        hostname=args.ip
    )
    
    # Keep running
    while True:
        time.sleep(1)
        
except Exception as e:
    log_json("error", "Connection failed",
        event_type="connection_failed",
        error=str(e),
        hostname=args.ip,
        troubleshooting_tips=[
            "Check if the device is on and connected to network",
            f"Verify the IP address: {args.ip}",
            "Ensure the device has TCP interface enabled",
            "Check firewall settings"
        ]
    )
finally:
    try:
        interface.close()
        log_json("info", "Connection closed",
            event_type="connection_closed"
        )
    except:
        pass