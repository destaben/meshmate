import time
import meshtastic
import meshtastic.tcp_interface
from pubsub import pub
from datetime import datetime
import json
import logging
import os
from handlers import PingHandler, MeteoHandler, InfoHandler, HelpHandler

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

# Initialize command handlers (will be set after parsing args)
command_handlers = []
monitored_channels = []
log_all_messages = False

def init_handlers(channels, log_all, aemet_api_key):
    """Initialize handlers based on configuration"""
    global command_handlers, monitored_channels, log_all_messages
    monitored_channels = [ch.lower() for ch in channels] if 'all' not in channels else ['all']
    log_all_messages = log_all
    
    # Initialize handlers - they can work on any channel now
    handlers = [
        PingHandler(),
        InfoHandler(), 
        HelpHandler()
    ]
    
    # Only add MeteoHandler if API key is provided
    if aemet_api_key:
        handlers.append(MeteoHandler(api_key=aemet_api_key))
    
    command_handlers = handlers

def should_process_channel(channel_name):
    """Check if we should process messages from this channel"""
    if 'all' in monitored_channels:
        return True
    return channel_name.lower() in monitored_channels

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
            
            # Check if we should process this channel
            if not should_process_channel(channel_name):
                return  # Skip messages from unmonitored channels
            
            # Log message in JSON format (only if configured or it's a command)
            is_command = message_text.strip().startswith('/')
            if log_all_messages or is_command:
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
                    message_id=packet.get('id'),
                    is_command=is_command
                )
            
            # Check if any handler can process this message
            for handler in command_handlers:
                if handler.can_handle(message_text, channel_name):
                    handler.handle(packet, interface, log_json)
                    break  # Only let the first matching handler process the message

def onConnection(interface, topic=pub.AUTO_TOPIC):
    log_json("info", "Connected to Meshtastic network",
        event_type="connection_established",
        status="connected"
    )

# Subscribe to events
pub.subscribe(onReceive, "meshtastic.receive")
pub.subscribe(onConnection, "meshtastic.connection.established")

# Get configuration from environment variables
meshtastic_ip = os.getenv('MESHTASTIC_IP')
meshtastic_hostname = os.getenv('MESHTASTIC_HOSTNAME')
channels = os.getenv('CHANNELS', 'iberia').split()
log_all_messages = os.getenv('LOG_ALL_MESSAGES', 'false').lower() == 'true'
aemet_api_key = os.getenv('AEMET_API_KEY')

# Determine connection target (IP takes priority over hostname)
connection_target = meshtastic_ip or meshtastic_hostname

if not connection_target:
    log_json("error", "Missing connection configuration", 
        event_type="config_error",
        error="Either MESHTASTIC_IP or MESHTASTIC_HOSTNAME environment variable must be set",
        troubleshooting_tips=[
            "Set MESHTASTIC_IP environment variable with device IP address",
            "OR set MESHTASTIC_HOSTNAME environment variable with device hostname",
            "Example: export MESHTASTIC_IP=192.168.1.230"
        ]
    )
    exit(1)

# Initialize handlers with configuration
init_handlers(channels, log_all_messages, aemet_api_key)

log_json("info", "Starting Meshtastic connection with auto-reconnect",
    event_type="startup",
    target_host=connection_target,
    monitored_channels=monitored_channels,
    log_all_messages=log_all_messages,
    meteo_enabled=aemet_api_key is not None,
    reconnect_interval=60
)

interface = None
reconnect_interval = 60  # seconds

def create_connection():
    """Create a new Meshtastic TCP interface"""
    global interface
    try:
        if interface:
            try:
                interface.close()
            except:
                pass
        
        interface = meshtastic.tcp_interface.TCPInterface(hostname=connection_target)
        log_json("info", "TCP interface created successfully",
            event_type="interface_created",
            hostname=connection_target
        )
        return True
    except Exception as e:
        log_json("error", "Failed to create interface",
            event_type="interface_creation_failed",
            error=str(e),
            hostname=connection_target
        )
        return False

def is_connection_healthy():
    """Check if the connection is still healthy"""
    try:
        if interface and hasattr(interface, 'socket') and interface.socket:
            # Try to get socket status
            return interface.socket.fileno() != -1
    except:
        pass
    return False

# Main connection loop with auto-reconnect
while True:
    try:
        # Create initial connection
        if not create_connection():
            log_json("warning", "Initial connection failed, retrying in 60 seconds",
                event_type="connection_retry_scheduled",
                retry_delay=reconnect_interval
            )
            time.sleep(reconnect_interval)
            continue
        
        # Main monitoring loop
        connection_start_time = time.time()
        last_health_check = time.time()
        
        while True:
            try:
                # Check connection health every 30 seconds
                current_time = time.time()
                if current_time - last_health_check > 30:
                    if not is_connection_healthy():
                        log_json("warning", "Connection health check failed",
                            event_type="connection_unhealthy",
                            uptime_seconds=int(current_time - connection_start_time)
                        )
                        break  # Break inner loop to reconnect
                    last_health_check = current_time
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                log_json("info", "Shutdown requested by user",
                    event_type="user_shutdown",
                    uptime_seconds=int(time.time() - connection_start_time)
                )
                raise
            except Exception as e:
                log_json("warning", "Error in monitoring loop",
                    event_type="monitoring_error",
                    error=str(e),
                    uptime_seconds=int(time.time() - connection_start_time)
                )
                break  # Break inner loop to reconnect
        
        # Connection lost, schedule reconnect
        log_json("warning", "Connection lost, reconnecting in 60 seconds",
            event_type="connection_lost",
            uptime_seconds=int(time.time() - connection_start_time),
            reconnect_delay=reconnect_interval
        )
        
        # Clean up current connection
        try:
            if interface:
                interface.close()
        except:
            pass
        
        time.sleep(reconnect_interval)
        
    except KeyboardInterrupt:
        log_json("info", "Shutting down gracefully",
            event_type="graceful_shutdown"
        )
        break
    except Exception as e:
        log_json("error", "Unexpected error in main loop",
            event_type="main_loop_error",
            error=str(e),
            reconnect_delay=reconnect_interval
        )
        time.sleep(reconnect_interval)

# Final cleanup
try:
    if interface:
        interface.close()
        log_json("info", "Connection closed",
            event_type="connection_closed"
        )
except Exception as e:
    log_json("warning", "Error during cleanup",
        event_type="cleanup_error",
        error=str(e)
    )