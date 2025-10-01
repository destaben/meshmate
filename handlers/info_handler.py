from .base_handler import BaseHandler
from typing import Dict, Any, Optional


class InfoHandler(BaseHandler):
    """Handler for /meshmate command - shows project information"""
    
    def __init__(self, channel=None):
        super().__init__(command='meshmate', channel=channel)
    
    def handle(self, packet: Dict[str, Any], interface, log_json) -> Optional[str]:
        """
        Handle meshmate info command
        """
        try:
            info = self.extract_packet_info(packet)
            
            # Log info command received
            log_json("info", "Info command received",
                event_type="info_command_received",
                sender_id=info['sender_id'],
                channel=info['channel'],
                command_text=info['message_text']
            )
            
            # Create project info message (optimized for Meshtastic limits)
            info_message = (
                "🤖 MeshMate Bot\n\n"
                "✨ Ping, avisos meteo, info\n"
                "🔗 github.com/destaben/meshmate\n\n"
                "¡Contribuye! 🚀"
            )
            
            # Send info message (no @ mention)
            interface.sendText(info_message, channelIndex=info['channel'])
            
            # Log successful response
            log_json("info", "Info response sent",
                event_type="info_response_sent",
                sender_id=info['sender_id'],
                original_message_id=info['message_id'],
                channel=info['channel'],
                message_length=len(info_message)
            )
            
        except Exception as e:
            # Log error
            log_json("error", "Error in info handler",
                error=str(e),
                sender_id=info.get('sender_id', 'unknown'),
                original_message_id=info.get('message_id', 'unknown'),
                channel=info.get('channel', 'unknown')
            )