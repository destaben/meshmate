"""
Prometheus metrics for MeshMate bot
"""
from prometheus_client import Counter, Gauge, Histogram, Info

# Bot information
bot_info = Info('meshmate_bot', 'MeshMate bot information')
bot_info.info({
    'version': '1.0.0',
    'name': 'MeshMate'
})

# Message metrics
messages_received_total = Counter(
    'meshmate_messages_received_total',
    'Total number of messages received',
    ['channel', 'sender']
)

messages_sent_total = Counter(
    'meshmate_messages_sent_total',
    'Total number of messages sent',
    ['channel']
)

# Command metrics
commands_processed_total = Counter(
    'meshmate_commands_processed_total',
    'Total number of commands processed',
    ['command', 'channel']
)

commands_failed_total = Counter(
    'meshmate_commands_failed_total',
    'Total number of failed commands',
    ['command', 'channel']
)

# Handler metrics
command_duration_seconds = Histogram(
    'meshmate_command_duration_seconds',
    'Time spent processing commands',
    ['command']
)

# Connection metrics
meshtastic_connection_status = Gauge(
    'meshmate_meshtastic_connection_status',
    'Meshtastic connection status (1=connected, 0=disconnected)'
)

meshtastic_reconnections_total = Counter(
    'meshmate_meshtastic_reconnections_total',
    'Total number of Meshtastic reconnection attempts'
)

# Schedule metrics
scheduled_tasks_total = Gauge(
    'meshmate_scheduled_tasks_total',
    'Total number of active scheduled tasks',
    ['user']
)

scheduled_tasks_executed_total = Counter(
    'meshmate_scheduled_tasks_executed_total',
    'Total number of executed scheduled tasks',
    ['user']
)

# HTTP API metrics
http_requests_total = Counter(
    'meshmate_http_requests_total',
    'Total number of HTTP API requests',
    ['endpoint', 'method', 'status']
)

# Signal quality metrics (from ping command)
signal_rssi = Gauge(
    'meshmate_signal_rssi',
    'Last received signal RSSI',
    ['sender', 'channel']
)

signal_snr = Gauge(
    'meshmate_signal_snr',
    'Last received signal SNR',
    ['sender', 'channel']
)

hops_used = Gauge(
    'meshmate_hops_used',
    'Number of hops used in last message',
    ['sender', 'channel']
)

# Error metrics
errors_total = Counter(
    'meshmate_errors_total',
    'Total number of errors',
    ['error_type']
)
