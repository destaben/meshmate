"""
Base handler class for MeshMate commands
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseHandler(ABC):
    """Base class for all command handlers"""
    
    def __init__(self, command: str, channel: str = None):
        """
        Initialize handler
        
        Args:
            command: The command this handler responds to (e.g., 'ping', 'meteo')
            channel: Optional channel restriction. If None, works in all channels
        """
        self.command = command.lower()
        self.channel = channel.lower() if channel else None
    
    def can_handle(self, message_text: str, channel_name: str) -> bool:
        """
        Check if this handler can process the given message
        
        Args:
            message_text: The text of the message
            channel_name: Name of the channel where message was sent
            
        Returns:
            True if this handler should process the message
        """
        # Check if message is our command
        if not message_text.strip().lower().startswith(f'/{self.command}'):
            return False
            
        # Check channel restriction if any
        if self.channel and channel_name.lower() != self.channel:
            return False
            
        return True
    
    @abstractmethod
    def handle(self, packet: Dict[str, Any], interface, log_json) -> Optional[str]:
        """
        Handle the command and return response message
        
        Args:
            packet: The complete message packet from Meshtastic
            interface: The Meshtastic interface for sending responses
            log_json: Function to log JSON messages
            
        Returns:
            Response message to send, or None if no response needed
        """
        pass
    
    def extract_packet_info(self, packet: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract common information from packet
        
        Args:
            packet: The message packet
            
        Returns:
            Dictionary with extracted information
        """
        return {
            'sender_id': packet.get('fromId', 'Unknown'),
            'message_text': packet.get('decoded', {}).get('text', ''),
            'channel': packet.get('channel', 0),
            'rx_time': packet.get('rxTime', 0),
            'hop_limit': packet.get('hopLimit', 0),
            'hop_start': packet.get('hopStart', 0),
            'via_mqtt': packet.get('viaMqtt', False),
            'rx_snr': packet.get('rxSnr'),
            'rx_rssi': packet.get('rxRssi'),
            'message_id': packet.get('id')
        }
    
    def mention_user(self, sender_id: str, response: str) -> str:
        """
        Add user mention to response
        
        Args:
            sender_id: ID of the user to mention
            response: The response message
            
        Returns:
            Response with user mention
        """
        node_name = sender_id.replace('!', '') if sender_id.startswith('!') else sender_id
        return f"@{node_name} {response}"