import time
import meshtastic
import meshtastic.tcp_interface
from pubsub import pub
from datetime import datetime, timedelta
import json
import logging
import os
import threading
from zoneinfo import ZoneInfo
from handlers import PingHandler, MeteoHandler, InfoHandler, HelpHandler, ScheduleHandler
from schedule_manager import ScheduleManager
from api_server import APIServer
import metrics

# Timezone configuration - always use Europe/Madrid
TIMEZONE = ZoneInfo("Europe/Madrid")

# Configure JSON logging
class JSONFormatter(logging.Formatter):
    def format(self, record):
        # Use Europe/Madrid timezone for all timestamps
        local_time = datetime.now(TIMEZONE)
        log_entry = {
            "timestamp": local_time.isoformat(),
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

import sys

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
schedule_manager = None

def init_handlers(channels, log_all, aemet_api_key):
    """Initialize handlers based on configuration"""
    global command_handlers, monitored_channels, log_all_messages, schedule_manager
    monitored_channels = [ch.lower() for ch in channels] if 'all' not in channels else ['all']
    log_all_messages = log_all
    
    # Initialize schedule manager
    schedule_manager = ScheduleManager()
    log_json("info", "Schedule manager initialized",
        event_type="schedule_manager_initialized",
        data_file=schedule_manager.data_file
    )
    
    # Initialize handlers - they can work on any channel now
    handlers = [
        PingHandler(),
        InfoHandler(), 
        HelpHandler(),
        ScheduleHandler(schedule_manager)
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
            
            # Update metrics for message received
            metrics.messages_received_total.labels(
                channel=f'channel_{channel}',
                sender=sender_id
            ).inc()
            
            # Update signal metrics if available
            if 'rxRssi' in packet:
                metrics.signal_rssi.labels(
                    sender=sender_id,
                    channel=f'channel_{channel}'
                ).set(packet['rxRssi'])
            
            if 'rxSnr' in packet:
                metrics.signal_snr.labels(
                    sender=sender_id,
                    channel=f'channel_{channel}'
                ).set(packet['rxSnr'])
            
            # Calculate and update hops
            if 'hopStart' in packet and 'hopLimit' in packet:
                hops = packet['hopStart'] - packet['hopLimit']
                metrics.hops_used.labels(
                    sender=sender_id,
                    channel=f'channel_{channel}'
                ).set(hops)
            
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
            
            # Convert timestamp to readable date in Europe/Madrid timezone
            if rx_time:
                timestamp = datetime.fromtimestamp(rx_time, TIMEZONE).strftime('%H:%M:%S %d/%m/%Y')
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
            handler_found = False
            for handler in command_handlers:
                handler_name = handler.__class__.__name__
                can_handle_result = handler.can_handle(message_text, channel_name)
                
                if is_command:  # Only log for commands to avoid spam
                    log_json("debug", "Checking handler",
                        event_type="handler_check",
                        handler=handler_name,
                        can_handle=can_handle_result,
                        command_text=message_text,
                        channel_name=channel_name
                    )
                
                if can_handle_result:
                    log_json("info", "Handler processing message",
                        event_type="handler_processing",
                        handler=handler_name,
                        sender_id=sender_id,
                        message_text=message_text
                    )
                    
                    # Track command processing start time
                    start_time = time.time()
                    
                    try:
                        handler.handle(packet, interface, log_json)
                        
                        # Update success metrics
                        command_name = message_text.split()[0].lstrip('/')
                        metrics.commands_processed_total.labels(
                            command=command_name,
                            channel=channel_name
                        ).inc()
                        
                        # Record command duration
                        duration = time.time() - start_time
                        metrics.command_duration_seconds.labels(
                            command=command_name
                        ).observe(duration)
                        
                    except Exception as e:
                        # Update error metrics
                        command_name = message_text.split()[0].lstrip('/')
                        metrics.commands_failed_total.labels(
                            command=command_name,
                            channel=channel_name
                        ).inc()
                        metrics.errors_total.labels(error_type='handler_error').inc()
                        raise
                    
                    handler_found = True
                    break  # Only let the first matching handler process the message
            
            if is_command and not handler_found:
                log_json("warning", "No handler found for command",
                    event_type="no_handler_found",
                    command_text=message_text,
                    available_handlers=[h.__class__.__name__ for h in command_handlers]
                )

def onConnection(interface, topic=pub.AUTO_TOPIC):
    log_json("info", "Connected to Meshtastic network",
        event_type="connection_established",
        status="connected"
    )
    # Update connection status metric
    metrics.meshtastic_connection_status.set(1)

# Subscribe to events
pub.subscribe(onReceive, "meshtastic.receive")
pub.subscribe(onConnection, "meshtastic.connection.established")

# Get configuration from environment variables
meshtastic_ip = os.getenv('MESHTASTIC_IP')
meshtastic_hostname = os.getenv('MESHTASTIC_HOSTNAME')
channels = os.getenv('CHANNELS', 'iberia').split()
log_all_messages = os.getenv('LOG_ALL_MESSAGES', 'false').lower() == 'true'
aemet_api_key = os.getenv('AEMET_API_KEY')
api_port = int(os.getenv('API_PORT', '8080'))
api_host = os.getenv('API_HOST', '0.0.0.0')

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

def cleanup_interface():
    global interface
    if interface:
        try:
            interface.close()
        except Exception:
            pass
        interface = None
        # Update connection status metric
        metrics.meshtastic_connection_status.set(0)

def create_connection():
    global interface
    cleanup_interface()
    try:
        log_json("info", "Creating new TCP interface",
            event_type="creating_interface",
            hostname=connection_target
        )
        interface = meshtastic.tcp_interface.TCPInterface(hostname=connection_target)
        if hasattr(interface, 'socket') and interface.socket:
            time.sleep(1)
            log_json("info", "TCP interface created successfully",
                event_type="interface_created",
                hostname=connection_target
            )
            return True
        else:
            log_json("error", "Interface created but no socket available",
                event_type="interface_creation_failed",
                hostname=connection_target
            )
            sys.exit(1)
    except Exception as e:
        log_json("error", "Failed to create interface",
            event_type="interface_creation_failed",
            error=str(e),
            hostname=connection_target
        )
        cleanup_interface()
        sys.exit(1)

def is_connection_healthy():
    try:
        if not interface:
            return False
        if not hasattr(interface, 'socket') or not interface.socket:
            return False
        try:
            fd = interface.socket.fileno()
            if fd == -1:
                return False
        except Exception:
            return False
        try:
            interface.socket.getpeername()
        except OSError:
            return False
        except Exception:
            return False
        return True
    except Exception as e:
        log_json("debug", "Connection health check failed",
            event_type="health_check_error",
            error=str(e)
        )
        sys.exit(1)

def safe_send_message(message: str, channel: int) -> bool:
    try:
        if not is_connection_healthy():
            log_json("error", "Cannot send message - connection unhealthy",
                event_type="send_message_failed",
                reason="unhealthy_connection"
            )
            sys.exit(1)
        interface.sendText(message, channelIndex=channel)
        # Update metrics for sent message
        metrics.messages_sent_total.labels(channel=f'channel_{channel}').inc()
        return True
    except Exception as e:
        log_json("error", "Error sending message",
            event_type="send_message_error",
            error=str(e)
        )
        metrics.errors_total.labels(error_type='send_message_error').inc()
        sys.exit(1)

def execute_scheduled_content(content: str, channel: int, user_id: str, schedule_id: int):
    """Execute scheduled content (command or message) with robust error handling"""
    try:
        if not interface or not is_connection_healthy():
            log_json("warning", "Cannot execute schedule - no healthy interface",
                event_type="schedule_execution_failed",
                user_id=user_id,
                schedule_id=schedule_id,
                reason="no_healthy_interface"
            )
            return
        
        if content.strip().startswith('/'):
            # It's a command - find matching handler
            for handler in command_handlers:
                if handler.can_handle(content, "scheduler"):
                    # Create a fake packet to simulate the command
                    fake_packet = {
                        'fromId': user_id,
                        'decoded': {
                            'text': content,
                            'portnum': 'TEXT_MESSAGE_APP'
                        },
                        'channel': channel,
                        'rxTime': int(time.time()),
                        'id': f"schedule_{schedule_id}_{int(time.time())}"
                    }
                    
                    log_json("info", "Executing scheduled command",
                        event_type="schedule_command_executed",
                        user_id=user_id,
                        schedule_id=schedule_id,
                        command=content,
                        channel=channel
                    )
                    
                    handler.handle(fake_packet, interface, log_json)
                    
                    # Update scheduled task metrics
                    metrics.scheduled_tasks_executed_total.labels(user=user_id).inc()
                    break
        else:
            # It's a regular message - send directly with safe wrapper
            message = f"⏰ Recordatorio: {content}"
            success = safe_send_message(message, channel)
            
            if success:
                log_json("info", "Executed scheduled reminder",
                    event_type="schedule_reminder_executed",
                    user_id=user_id,
                    schedule_id=schedule_id,
                    reminder_content=content,
                    channel=channel
                )
                # Update scheduled task metrics
                metrics.scheduled_tasks_executed_total.labels(user=user_id).inc()
            else:
                log_json("warning", "Failed to send scheduled reminder",
                    event_type="schedule_reminder_failed",
                    user_id=user_id,
                    schedule_id=schedule_id,
                    reminder_content=content,
                    channel=channel
                )
            
    except Exception as e:
        log_json("error", "Error executing schedule",
            event_type="schedule_execution_error",
            error=str(e),
            user_id=user_id,
            schedule_id=schedule_id,
            content=content
        )
        metrics.errors_total.labels(error_type='schedule_execution_error').inc()

def schedule_worker():
    log_json("info", "Schedule worker started",
        event_type="schedule_worker_started"
    )
    while True:
        if schedule_manager:
            due_schedules = schedule_manager.get_due_schedules()
            for schedule in due_schedules:
                execute_scheduled_content(
                    schedule['content'],
                    schedule['channel'],
                    schedule['user_id'],
                    schedule['id']
                )
        current_time = datetime.now(TIMEZONE)
        next_minute = current_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
        sleep_seconds = (next_minute - current_time).total_seconds()
        time.sleep(max(1, sleep_seconds))


# Start schedule worker thread
schedule_thread = threading.Thread(target=schedule_worker, daemon=True)
schedule_thread.start()

log_json("info", "Schedule worker thread started",
    event_type="schedule_thread_started"
)

# Initialize and start API server
api_server = APIServer(port=api_port, host=api_host)
api_server.set_log_function(log_json)

log_json("info", "Starting API server",
    event_type="api_server_init",
    host=api_host,
    port=api_port
)

# Single connection attempt, exit on failure
if not create_connection():
    log_json("error", "Initial connection failed, exiting",
        event_type="connection_failed"
    )
    sys.exit(1)

# Set the meshtastic interface in the API server after successful connection
api_server.set_meshtastic_interface(interface)

# Start API server in background thread
api_server.run_in_thread()

# Main monitoring loop
connection_start_time = time.time()
last_health_check = time.time()
while True:
    try:
        health_check_interval = 30
        current_time = time.time()
        if current_time - last_health_check > health_check_interval:
            if not is_connection_healthy():
                log_json("error", "Connection health check failed, exiting",
                    event_type="connection_unhealthy",
                    uptime_seconds=int(current_time - connection_start_time)
                )
                cleanup_interface()
                sys.exit(1)
            last_health_check = current_time
        time.sleep(1)
    except KeyboardInterrupt:
        log_json("info", "Shutting down gracefully",
            event_type="graceful_shutdown"
        )
        cleanup_interface()
        break
    except Exception as e:
        log_json("error", "Unexpected error in main loop, exiting",
            event_type="main_loop_error",
            error=str(e)
        )
        cleanup_interface()
        sys.exit(1)