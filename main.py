import time
import meshtastic
import meshtastic.tcp_interface
from pubsub import pub
from datetime import datetime, timedelta
import json
import logging
import os
import threading
from handlers import PingHandler, MeteoHandler, InfoHandler, HelpHandler, ScheduleHandler
from schedule_manager import ScheduleManager

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

# Suppress BrokenPipeError from meshtastic threads
import sys
original_excepthook = sys.excepthook

def custom_excepthook(exctype, value, traceback):
    """Custom exception handler to suppress BrokenPipeError from meshtastic heartbeat threads"""
    if exctype == BrokenPipeError:
        # Log it as a debug message instead of letting it print to stderr
        log_json("debug", "Suppressed BrokenPipeError from background thread",
            event_type="suppressed_broken_pipe",
            error=str(value)
        )
        return
    
    # For all other exceptions, use the original handler
    original_excepthook(exctype, value, traceback)

# Install our custom exception handler
sys.excepthook = custom_excepthook

# Also handle thread exceptions
def thread_exception_handler(args):
    """Handle exceptions in threads, particularly for meshtastic heartbeat errors"""
    if args.exc_type == BrokenPipeError:
        log_json("debug", "Suppressed BrokenPipeError from thread",
            event_type="suppressed_thread_broken_pipe",
            thread_name=args.thread.name if args.thread else "unknown",
            error=str(args.exc_value)
        )
        return
    
    # Log other thread exceptions
    log_json("error", "Unhandled thread exception",
        event_type="thread_exception",
        thread_name=args.thread.name if args.thread else "unknown",
        exception_type=args.exc_type.__name__ if args.exc_type else "unknown",
        error=str(args.exc_value)
    )

# Install thread exception handler (Python 3.8+)
if hasattr(threading, 'excepthook'):
    threading.excepthook = thread_exception_handler

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
                    handler.handle(packet, interface, log_json)
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

def cleanup_interface():
    """Aggressively cleanup the current interface"""
    global interface
    if interface:
        try:
            # Try to close gracefully first
            interface.close()
        except:
            pass
        
        try:
            # Force close socket if it exists
            if hasattr(interface, 'socket') and interface.socket:
                interface.socket.close()
        except:
            pass
        
        # Clear the interface
        interface = None
        
        # Give time for threads to cleanup
        time.sleep(2)

def create_connection():
    """Create a new Meshtastic TCP interface with robust cleanup"""
    global interface
    
    # Aggressive cleanup first
    cleanup_interface()
    
    try:
        log_json("info", "Creating new TCP interface",
            event_type="creating_interface",
            hostname=connection_target
        )
        
        interface = meshtastic.tcp_interface.TCPInterface(hostname=connection_target)
        
        # Test the connection immediately
        if hasattr(interface, 'socket') and interface.socket:
            # Give it a moment to establish
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
            return False
            
    except Exception as e:
        log_json("error", "Failed to create interface",
            event_type="interface_creation_failed",
            error=str(e),
            hostname=connection_target
        )
        cleanup_interface()
        return False

def is_connection_healthy():
    """Check if the connection is still healthy with multiple tests"""
    try:
        if not interface:
            return False
            
        if not hasattr(interface, 'socket') or not interface.socket:
            return False
        
        # Test 1: Check socket file descriptor
        try:
            fd = interface.socket.fileno()
            if fd == -1:
                return False
        except:
            return False
        
        # Test 2: Check socket state
        try:
            interface.socket.getpeername()
        except OSError:
            # Socket is not connected
            return False
        except:
            return False
        
        return True
        
    except Exception as e:
        log_json("debug", "Connection health check failed",
            event_type="health_check_error",
            error=str(e)
        )
        return False

def safe_send_message(message: str, channel: int) -> bool:
    """Safely send a message with connection health checks"""
    try:
        if not is_connection_healthy():
            log_json("warning", "Cannot send message - connection unhealthy",
                event_type="send_message_failed",
                reason="unhealthy_connection"
            )
            return False
            
        interface.sendText(message, channelIndex=channel)
        return True
        
    except (BrokenPipeError, ConnectionResetError, OSError) as e:
        log_json("warning", "Connection error while sending message",
            event_type="send_message_connection_error", 
            error=str(e),
            message_preview=message[:50] + "..." if len(message) > 50 else message
        )
        return False
    except Exception as e:
        log_json("error", "Unexpected error sending message",
            event_type="send_message_unexpected_error",
            error=str(e)
        )
        return False

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

def schedule_worker():
    """Background worker that checks and executes schedules every minute"""
    log_json("info", "Schedule worker started",
        event_type="schedule_worker_started"
    )
    
    while True:
        try:
            if schedule_manager:
                due_schedules = schedule_manager.get_due_schedules()
                
                for schedule in due_schedules:
                    execute_scheduled_content(
                        schedule['content'],
                        schedule['channel'],
                        schedule['user_id'],
                        schedule['id']
                    )
            
            # Wait until the next minute
            current_time = datetime.now()
            next_minute = current_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
            sleep_seconds = (next_minute - current_time).total_seconds()
            time.sleep(max(1, sleep_seconds))
            
        except Exception as e:
            log_json("error", "Error in schedule worker",
                event_type="schedule_worker_error",
                error=str(e)
            )
            time.sleep(60)  # Wait a minute before retrying

# Connection failure tracking for restart decision
connection_failures = 0
last_failure_reset = time.time()
MAX_FAILURES_BEFORE_RESTART = 10
FAILURE_RESET_INTERVAL = 3600  # Reset failure count every hour

def should_restart_process():
    """Check if we should restart the entire process due to too many failures"""
    global connection_failures, last_failure_reset
    
    current_time = time.time()
    
    # Reset failure count every hour
    if current_time - last_failure_reset > FAILURE_RESET_INTERVAL:
        connection_failures = 0
        last_failure_reset = current_time
        log_json("info", "Connection failure counter reset",
            event_type="failure_counter_reset"
        )
    
    connection_failures += 1
    
    if connection_failures >= MAX_FAILURES_BEFORE_RESTART:
        log_json("critical", "Too many connection failures, process restart recommended",
            event_type="process_restart_recommended",
            failure_count=connection_failures,
            max_failures=MAX_FAILURES_BEFORE_RESTART
        )
        return True
    
    return False

# Start schedule worker thread
schedule_thread = threading.Thread(target=schedule_worker, daemon=True)
schedule_thread.start()

log_json("info", "Schedule worker thread started",
    event_type="schedule_thread_started"
)

# Main connection loop with auto-reconnect and restart protection
while True:
    try:
        # Create initial connection
        if not create_connection():
            log_json("warning", "Initial connection failed, retrying in 60 seconds",
                event_type="connection_retry_scheduled",
                retry_delay=reconnect_interval
            )
            
            # Check if we should restart the process
            if should_restart_process():
                log_json("critical", "Initiating process restart due to connection failures",
                    event_type="process_restarting"
                )
                cleanup_interface()
                sys.exit(1)  # Exit with error code to trigger container restart
            
            time.sleep(reconnect_interval)
            continue
        
        # Main monitoring loop
        connection_start_time = time.time()
        last_health_check = time.time()
        consecutive_failures = 0
        
        while True:
            try:
                # Check connection health more frequently after failures
                health_check_interval = 10 if consecutive_failures > 0 else 30
                current_time = time.time()
                
                if current_time - last_health_check > health_check_interval:
                    if not is_connection_healthy():
                        consecutive_failures += 1
                        log_json("warning", f"Connection health check failed (attempt {consecutive_failures})",
                            event_type="connection_unhealthy",
                            uptime_seconds=int(current_time - connection_start_time),
                            consecutive_failures=consecutive_failures
                        )
                        
                        # Break immediately on health check failure
                        break
                    else:
                        # Reset failure counter on successful health check
                        if consecutive_failures > 0:
                            log_json("info", "Connection health restored",
                                event_type="connection_health_restored",
                                uptime_seconds=int(current_time - connection_start_time)
                            )
                            consecutive_failures = 0
                        
                    last_health_check = current_time
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                log_json("info", "Shutdown requested by user",
                    event_type="user_shutdown",
                    uptime_seconds=int(time.time() - connection_start_time)
                )
                raise
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                log_json("warning", "Connection error detected in monitoring loop",
                    event_type="monitoring_connection_error",
                    error=str(e),
                    uptime_seconds=int(time.time() - connection_start_time)
                )
                break  # Break inner loop to reconnect immediately
            except Exception as e:
                log_json("warning", "Unexpected error in monitoring loop",
                    event_type="monitoring_unexpected_error",
                    error=str(e),
                    uptime_seconds=int(time.time() - connection_start_time)
                )
                break  # Break inner loop to reconnect
        
        # Connection lost, schedule reconnect
        uptime = int(time.time() - connection_start_time)
        log_json("warning", "Connection lost, reconnecting",
            event_type="connection_lost",
            uptime_seconds=uptime,
            reconnect_delay=reconnect_interval
        )
        
        # Aggressive cleanup of current connection
        cleanup_interface()
        
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