"""
HTTP API server for MeshMate bot
Provides endpoints for:
- Prometheus metrics scraping (/metrics)
- Sending messages via HTTP (/send)
- Health check (/health)
"""
from flask import Flask, request, jsonify
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import logging
import threading
from typing import Optional, Callable

logger = logging.getLogger('meshmate.api')

class APIServer:
    """Flask-based HTTP API server for MeshMate"""
    
    def __init__(self, port: int = 8080, host: str = '0.0.0.0'):
        """
        Initialize API server
        
        Args:
            port: Port to listen on (default: 8080)
            host: Host to bind to (default: 0.0.0.0)
        """
        self.port = port
        self.host = host
        self.app = Flask('meshmate-api')
        self.meshtastic_interface = None
        self.log_json = None
        
        # Setup routes
        self._setup_routes()
        
        # Disable Flask's default logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        
    def set_meshtastic_interface(self, interface):
        """Set the Meshtastic interface for sending messages"""
        self.meshtastic_interface = interface
        
    def set_log_function(self, log_json: Callable):
        """Set the JSON logging function"""
        self.log_json = log_json
        
    def _setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/metrics', methods=['GET'])
        def metrics():
            """Prometheus metrics endpoint"""
            from metrics import http_requests_total
            http_requests_total.labels(endpoint='/metrics', method='GET', status='200').inc()
            return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}
        
        @self.app.route('/health', methods=['GET'])
        def health():
            """Health check endpoint"""
            from metrics import http_requests_total, meshtastic_connection_status
            http_requests_total.labels(endpoint='/health', method='GET', status='200').inc()
            
            # Check if Meshtastic is connected
            is_connected = self.meshtastic_interface is not None
            
            return jsonify({
                'status': 'healthy' if is_connected else 'degraded',
                'meshtastic_connected': is_connected,
                'version': '1.0.0'
            }), 200
        
        @self.app.route('/send', methods=['POST'])
        def send_message():
            """
            Send a message via Meshtastic
            
            Expected JSON body:
            {
                "text": "Message text",
                "channel": 1  // optional, defaults to 0 (primary)
            }
            """
            from metrics import http_requests_total, messages_sent_total
            
            try:
                # Check if Meshtastic interface is available
                if not self.meshtastic_interface:
                    http_requests_total.labels(endpoint='/send', method='POST', status='503').inc()
                    return jsonify({
                        'error': 'Meshtastic interface not available'
                    }), 503
                
                # Parse request
                data = request.get_json()
                if not data:
                    http_requests_total.labels(endpoint='/send', method='POST', status='400').inc()
                    return jsonify({
                        'error': 'No JSON data provided'
                    }), 400
                
                text = data.get('text')
                channel = data.get('channel', 0)
                
                if not text:
                    http_requests_total.labels(endpoint='/send', method='POST', status='400').inc()
                    return jsonify({
                        'error': 'Missing required field: text'
                    }), 400
                
                # Validate channel
                if not isinstance(channel, int) or channel < 0:
                    http_requests_total.labels(endpoint='/send', method='POST', status='400').inc()
                    return jsonify({
                        'error': 'Channel must be a non-negative integer'
                    }), 400
                
                # Send message
                try:
                    self.meshtastic_interface.sendText(
                        text=text,
                        channelIndex=channel
                    )
                    
                    # Update metrics
                    messages_sent_total.labels(channel=f'channel_{channel}').inc()
                    http_requests_total.labels(endpoint='/send', method='POST', status='200').inc()
                    
                    # Log success
                    if self.log_json:
                        self.log_json("info", "Message sent via HTTP API",
                            event_type="http_message_sent",
                            text=text,
                            channel=channel
                        )
                    
                    return jsonify({
                        'success': True,
                        'message': 'Message sent successfully',
                        'channel': channel
                    }), 200
                    
                except Exception as e:
                    http_requests_total.labels(endpoint='/send', method='POST', status='500').inc()
                    
                    if self.log_json:
                        self.log_json("error", f"Failed to send message via Meshtastic: {str(e)}",
                            event_type="http_message_send_failed",
                            error=str(e)
                        )
                    
                    return jsonify({
                        'error': f'Failed to send message: {str(e)}'
                    }), 500
                    
            except Exception as e:
                http_requests_total.labels(endpoint='/send', method='POST', status='500').inc()
                
                if self.log_json:
                    self.log_json("error", f"HTTP API error: {str(e)}",
                        event_type="http_api_error",
                        error=str(e)
                    )
                
                return jsonify({
                    'error': f'Internal server error: {str(e)}'
                }), 500
        
        @self.app.route('/info', methods=['GET'])
        def info():
            """Get bot information"""
            from metrics import http_requests_total
            http_requests_total.labels(endpoint='/info', method='GET', status='200').inc()
            
            return jsonify({
                'name': 'MeshMate',
                'version': '1.0.0',
                'endpoints': {
                    '/metrics': 'Prometheus metrics (GET)',
                    '/health': 'Health check (GET)',
                    '/send': 'Send message (POST)',
                    '/info': 'Bot information (GET)'
                }
            }), 200
    
    def run(self):
        """Run the Flask server (blocking)"""
        if self.log_json:
            self.log_json("info", f"Starting HTTP API server on {self.host}:{self.port}",
                event_type="api_server_starting",
                host=self.host,
                port=self.port
            )
        
        self.app.run(
            host=self.host,
            port=self.port,
            debug=False,
            use_reloader=False
        )
    
    def run_in_thread(self):
        """Run the Flask server in a separate thread"""
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        
        if self.log_json:
            self.log_json("info", "HTTP API server started in background thread",
                event_type="api_server_started",
                host=self.host,
                port=self.port
            )
        
        return thread
