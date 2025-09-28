"""
Ping command handler for MeshMate
"""
from typing import Dict, Any, Optional
from .base_handler import BaseHandler


class PingHandler(BaseHandler):
    """Handler for /ping command"""
    
    def __init__(self, channel=None):
        super().__init__(command='ping', channel=channel)
    
    def handle(self, packet: Dict[str, Any], interface, log_json) -> Optional[str]:
        """
        Handle ping command and send response with hop and signal information
        
        Args:
            packet: The message packet
            interface: Meshtastic interface for sending responses
            log_json: Function to log JSON messages
            
        Returns:
            Response message (though it's sent directly via interface)
        """
        try:
            # Extract packet information
            info = self.extract_packet_info(packet)
            
            # Calculate hops used (hopStart - hopLimit)
            hops_used = info['hop_start'] - info['hop_limit'] if info['hop_start'] > 0 else 0
            
            # Build response message
            response = "pong"
            
            # Add reception method
            if info['via_mqtt']:
                response += " (via MQTT)"
            else:
                response += " (via radio)"
            
            # Add hop information
            if info['hop_start'] > 0:
                response += f" - {hops_used}/{info['hop_start']} hops"
            
            # Add signal info if available
            signal_info = []
            if info['rx_snr'] is not None:
                signal_info.append(f"SNR: {info['rx_snr']}dB")
            if info['rx_rssi'] is not None:
                signal_info.append(f"RSSI: {info['rx_rssi']}dBm")
            
            if signal_info:
                response += f" ({', '.join(signal_info)})"
            
            # Add user mention
            final_response = self.mention_user(info['sender_id'], response)
            
            # Send response
            interface.sendText(final_response, channelIndex=info['channel'])
            
            # Log successful response
            log_json("info", "Ping response sent",
                event_type="ping_response_sent",
                response_text=final_response,
                original_message_id=info['message_id'],
                sender_id=info['sender_id'],
                channel=info['channel'],
                hops_used=hops_used,
                hop_start=info['hop_start'],
                hop_limit=info['hop_limit'],
                via_mqtt=info['via_mqtt'],
                rx_snr=info['rx_snr'],
                rx_rssi=info['rx_rssi']
            )
            
            return final_response
            
        except Exception as e:
            # Log error
            info = self.extract_packet_info(packet)
            log_json("error", "Error sending ping reply",
                event_type="ping_response_error",
                error=str(e),
                sender_id=info['sender_id'],
                original_message_id=info['message_id']
            )
            return None