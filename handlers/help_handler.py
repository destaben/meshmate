from .base_handler import BaseHandler
from typing import Dict, Any, Optional


class HelpHandler(BaseHandler):
    """Handler for /? command - shows available commands"""
    
    def __init__(self, channel=None):
        super().__init__(command='?', channel=channel)
    
    def handle(self, packet: Dict[str, Any], interface, log_json) -> Optional[str]:
        """
        Handle help command
        """
        try:
            info = self.extract_packet_info(packet)
            
            # Log help command received
            log_json("info", "Help command received",
                event_type="help_command_received",
                sender_id=info['sender_id'],
                channel=info['channel'],
                command_text=info['message_text']
            )
            
            # Create help message with available commands
            help_message = (
                "📋 Comandos disponibles:\n\n"
                "/ping - Test de conectividad\n\n"
                "/meteo - Avisos rojos AEMET\n\n"
                "/schedule - Programar comandos\n\n"
                "/meshmate - Info del proyecto\n\n"
                "/? - Esta ayuda\n\n"
                "🤖 MeshMate Bot"
            )
            
            # Send help message (no @ mention)
            interface.sendText(help_message, channelIndex=info['channel'])
            
            # Log successful response
            log_json("info", "Help response sent",
                event_type="help_response_sent",
                sender_id=info['sender_id'],
                original_message_id=info['message_id'],
                channel=info['channel'],
                message_length=len(help_message)
            )
            
        except Exception as e:
            # Log error
            log_json("error", "Error in help handler",
                error=str(e),
                sender_id=info.get('sender_id', 'unknown'),
                original_message_id=info.get('message_id', 'unknown'),
                channel=info.get('channel', 'unknown')
            )