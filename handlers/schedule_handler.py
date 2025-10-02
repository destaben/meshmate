from .base_handler import BaseHandler
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from schedule_manager import ScheduleManager

class ScheduleHandler(BaseHandler):
    """Handler for /schedule command - manages scheduled commands and reminders"""
    
    def __init__(self, schedule_manager: 'ScheduleManager', channel=None):
        super().__init__(command='schedule', channel=channel)
        self.schedule_manager = schedule_manager
        print(f"ScheduleHandler initialized with command='{self.command}' and schedule_manager={schedule_manager is not None}")
    
    def handle(self, packet: Dict[str, Any], interface, log_json) -> Optional[str]:
        """
        Handle schedule command
        
        Supported formats:
        /schedule add HH:MM command/text - Add new schedule
        /schedule list - List user's schedules  
        /schedule del ID - Delete schedule by ID
        /schedule help - Show help
        """
        log_json("info", "ScheduleHandler.handle() called",
            event_type="schedule_handler_invoked",
            packet_id=packet.get('id', 'unknown')
        )
        
        try:
            info = self.extract_packet_info(packet)
            user_id = info['sender_id']
            message_parts = info['message_text'].strip().split()
            
            # Log schedule command received
            log_json("info", "Schedule command received",
                event_type="schedule_command_received",
                sender_id=user_id,
                channel=info['channel'],
                command_text=info['message_text']
            )
            
            # Parse subcommand
            log_json("debug", "Parsing schedule command",
                event_type="schedule_parsing",
                message_parts=message_parts,
                parts_count=len(message_parts)
            )
            
            if len(message_parts) < 2:
                log_json("debug", "No subcommand provided, showing help",
                    event_type="schedule_no_subcommand"
                )
                response = self._show_help()
            else:
                subcommand = message_parts[1].lower()
                
                log_json("debug", "Processing schedule subcommand",
                    event_type="schedule_subcommand",
                    subcommand=subcommand
                )
                
                if subcommand == 'add':
                    response = self._handle_add(message_parts[2:], user_id, info['channel'])
                elif subcommand == 'list':
                    response = self._handle_list(user_id)
                elif subcommand == 'del' or subcommand == 'delete':
                    response = self._handle_delete(message_parts[2:], user_id)
                elif subcommand == 'help':
                    response = self._show_help()
                else:
                    response = f"Subcomando '{subcommand}' no reconocido. Usa /schedule help"
            
            # Send response (no @ mention)
            try:
                interface.sendText(response, channelIndex=info['channel'])
            except Exception as send_error:
                log_json("error", "Failed to send schedule response",
                    event_type="schedule_response_send_failed",
                    error=str(send_error),
                    sender_id=user_id,
                    channel=info['channel'],
                    response_preview=response[:50] + "..." if len(response) > 50 else response
                )
            
            # Log successful response
            log_json("info", "Schedule response sent",
                event_type="schedule_response_sent",
                sender_id=user_id,
                original_message_id=info['message_id'],
                channel=info['channel'],
                subcommand=message_parts[1] if len(message_parts) > 1 else 'none',
                message_length=len(response)
            )
            
        except Exception as e:
            # Log error
            log_json("error", "Error in schedule handler",
                error=str(e),
                sender_id=info.get('sender_id', 'unknown'),
                original_message_id=info.get('message_id', 'unknown'),
                channel=info.get('channel', 'unknown')
            )
    
    def _handle_add(self, args: list, user_id: str, channel: int) -> str:
        """Handle 'add' subcommand"""
        if len(args) < 2:
            return "❌ Formato: add HH:MM texto [días]"
        
        time_str = args[0]
        
        # Check if last argument is weekdays (contains day names or "all")
        weekdays = None
        content_args = args[1:]
        
        # Spanish weekdays and "all" to detect
        spanish_days = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']
        
        if len(content_args) > 1:
            last_arg = content_args[-1].lower()
            # Check if last argument contains any Spanish weekday or "all"
            if last_arg == 'all' or any(day in last_arg for day in spanish_days):
                weekdays = content_args[-1]
                content_args = content_args[:-1]
        
        content = ' '.join(content_args)
        
        if not content.strip():
            return "❌ Falta comando/texto"
        
        result = self.schedule_manager.add_schedule(user_id, time_str, content, channel, weekdays)
        
        if result['success']:
            content_preview = content[:25] + '...' if len(content) > 25 else content
            return f"✅ {result['message']}\n\n\ {content_preview}"
        else:
            return f"❌ {result['message']}"
    
    def _handle_list(self, user_id: str) -> str:
        """Handle 'list' subcommand"""
        schedules = self.schedule_manager.list_schedules(user_id)
        
        if not schedules:
            return "📋 Sin schedules\n\nUsa: add HH:MM texto [días]"
        
        response = "📋 Tus schedules:\n\n"
        for schedule in schedules:
            time_str = schedule['time'].strftime('%H:%M')
            content = schedule['content'][:20] + '...' if len(schedule['content']) > 20 else schedule['content']
            icon = '🤖' if schedule['is_command'] else '💬'
            
            # Add recurring/one-time indicator
            if schedule.get('is_recurring', False):
                weekdays = schedule.get('weekdays', [])
                if len(weekdays) == 7:
                    recurrence = "(todos los días)"
                else:
                    days = ', '.join(schedule.get('weekday_names', []))
                    recurrence = f"({days})"
            else:
                recurrence = "(una vez)"
            
            response += f"{icon} #{schedule['id']} {time_str} {content} {recurrence}\n"
        
        response += f"\nUsa: del ID"
        return response
    
    def _handle_delete(self, args: list, user_id: str) -> str:
        """Handle 'delete' subcommand"""
        if not args:
            return "❌ Formato: del ID"
        
        try:
            schedule_id = int(args[0])
            result = self.schedule_manager.delete_schedule(user_id, schedule_id)
            
            if result['success']:
                return f"✅ {result['message']}"
            else:
                return f"❌ {result['message']}"
                
        except ValueError:
            return "❌ ID debe ser un número"
    
    def _show_help(self) -> str:
        """Show help message"""
        return (
            "📅 /schedule\n\n"
            "• add HH:MM texto [días]\n\n"
            "• list\n\n"
            "• del ID\n\n"
            "Ej: /schedule add 09:30 /ping all"
        )