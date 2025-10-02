import json
import os
from datetime import datetime, time
from typing import Dict, List, Optional, Any
import threading


class ScheduleManager:
    """Manages scheduled commands and reminders for users"""
    
    # Spanish weekdays mapping
    SPANISH_WEEKDAYS = {
        'lunes': 0,      # Monday
        'martes': 1,     # Tuesday
        'miercoles': 2,  # Wednesday
        'jueves': 3,     # Thursday
        'viernes': 4,    # Friday
        'sabado': 5,     # Saturday
        'domingo': 6     # Sunday
    }
    
    def __init__(self, data_file=None):
        if data_file is None:
            # Use data directory if it exists (Docker volume), otherwise current directory
            data_dir = 'data' if os.path.exists('data') else '.'
            # Create data directory if it doesn't exist
            if not os.path.exists(data_dir):
                os.makedirs(data_dir, exist_ok=True)
            self.data_file = os.path.join(data_dir, 'schedules.json')
        else:
            self.data_file = data_file
        self.schedules = {}  # {user_id: [schedule_objects]}
        self.lock = threading.Lock()
        self.max_schedules_per_user = 5
        self.load_schedules()
    
    def load_schedules(self):
        """Load schedules from JSON file"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Convert time strings back to time objects
                    for user_id, user_schedules in data.items():
                        self.schedules[user_id] = []
                        for schedule in user_schedules:
                            schedule['time'] = datetime.strptime(schedule['time'], '%H:%M').time()
                            self.schedules[user_id].append(schedule)
        except Exception as e:
            print(f"Error loading schedules: {e}")
            self.schedules = {}
    
    def save_schedules(self):
        """Save schedules to JSON file"""
        try:
            # Convert time objects to strings for JSON serialization
            data = {}
            for user_id, user_schedules in self.schedules.items():
                data[user_id] = []
                for schedule in user_schedules:
                    schedule_copy = schedule.copy()
                    schedule_copy['time'] = schedule['time'].strftime('%H:%M')
                    data[user_id].append(schedule_copy)
            
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving schedules: {e}")
    
    def add_schedule(self, user_id: str, time_str: str, content: str, channel: int, weekdays: str = None) -> Dict[str, Any]:
        """
        Add a new schedule for a user
        
        Args:
            user_id: User identifier
            time_str: Time in HH:MM format
            content: Command or message to execute/send
            channel: Channel where the schedule was created
            weekdays: Days of week in Spanish (e.g., "lunes,miercoles,viernes" or None for one-time)
            
        Returns:
            Dict with success status and message
        """
        with self.lock:
            try:
                # Parse time
                schedule_time = datetime.strptime(time_str, '%H:%M').time()
                
                # Parse and validate weekdays if provided
                parsed_weekdays = None
                weekday_names = []
                if weekdays:
                    weekdays_input = weekdays.strip().lower()
                    
                    # Handle "all" special case
                    if weekdays_input == 'all':
                        parsed_weekdays = list(range(7))  # All days 0-6
                        weekday_names = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']
                    else:
                        weekday_names = [day.strip().lower() for day in weekdays.split(',')]
                        parsed_weekdays = []
                        
                        for day_name in weekday_names:
                            if day_name not in self.SPANISH_WEEKDAYS:
                                return {
                                    'success': False,
                                    'message': f'Día inválido: {day_name}. Usa días en español o "all"'
                                }
                            parsed_weekdays.append(self.SPANISH_WEEKDAYS[day_name])
                
                # Check user limits
                if user_id not in self.schedules:
                    self.schedules[user_id] = []
                
                if len(self.schedules[user_id]) >= self.max_schedules_per_user:
                    return {
                        'success': False,
                        'message': f'Límite alcanzado ({self.max_schedules_per_user} schedules máximo)'
                    }
                
                # Create schedule object
                schedule_id = len(self.schedules[user_id]) + 1
                schedule = {
                    'id': schedule_id,
                    'time': schedule_time,
                    'content': content,
                    'channel': channel,
                    'created_at': datetime.now().isoformat(),
                    'is_command': content.strip().startswith('/'),
                    'active': True,
                    'weekdays': parsed_weekdays,  # None for one-time, list of numbers for recurring
                    'weekday_names': weekday_names,  # For display purposes
                    'is_recurring': parsed_weekdays is not None,
                    'executed_dates': []  # Track when one-time schedules were executed
                }
                
                self.schedules[user_id].append(schedule)
                self.save_schedules()
                
                # Create appropriate success message
                if parsed_weekdays is not None:
                    if len(parsed_weekdays) == 7:
                        days_str = "todos los días"
                    else:
                        days_str = ', '.join(weekday_names)
                    message = f'Schedule #{schedule_id} creado para {time_str} los {days_str} (recurrente)'
                else:
                    message = f'Schedule #{schedule_id} creado para {time_str} (una vez)'
                
                return {
                    'success': True,
                    'message': message,
                    'schedule': schedule
                }
                
            except ValueError:
                return {
                    'success': False,
                    'message': 'Formato de hora inválido. Usa HH:MM (ej: 09:30)'
                }
            except Exception as e:
                return {
                    'success': False,
                    'message': f'Error creando schedule: {str(e)}'
                }
    
    def list_schedules(self, user_id: str) -> List[Dict[str, Any]]:
        """List all schedules for a user"""
        with self.lock:
            if user_id not in self.schedules:
                return []
            return [s for s in self.schedules[user_id] if s['active']]
    
    def delete_schedule(self, user_id: str, schedule_id: int) -> Dict[str, Any]:
        """Delete a schedule by ID"""
        with self.lock:
            if user_id not in self.schedules:
                return {
                    'success': False,
                    'message': 'No tienes schedules'
                }
            
            for schedule in self.schedules[user_id]:
                if schedule['id'] == schedule_id and schedule['active']:
                    schedule['active'] = False
                    self.save_schedules()
                    return {
                        'success': True,
                        'message': f'Schedule #{schedule_id} eliminado'
                    }
            
            return {
                'success': False,
                'message': f'Schedule #{schedule_id} no encontrado'
            }
    
    def get_due_schedules(self) -> List[Dict[str, Any]]:
        """Get all schedules that should be executed now"""
        with self.lock:
            current_datetime = datetime.now()
            current_time = current_datetime.time()
            current_minute = current_time.replace(second=0, microsecond=0)
            current_weekday = current_datetime.weekday()  # 0=Monday, 6=Sunday
            today_str = current_datetime.strftime('%Y-%m-%d')
            
            due_schedules = []
            schedules_to_deactivate = []  # Track one-time schedules to deactivate
            
            for user_id, user_schedules in self.schedules.items():
                for i, schedule in enumerate(user_schedules):
                    if not schedule['active']:
                        continue
                        
                    if schedule['time'].replace(second=0, microsecond=0) != current_minute:
                        continue
                    
                    # Handle recurring schedules (with weekdays)
                    if schedule.get('is_recurring', False) and schedule.get('weekdays'):
                        if current_weekday in schedule['weekdays']:
                            due_schedule = schedule.copy()
                            due_schedule['user_id'] = user_id
                            due_schedules.append(due_schedule)
                    
                    # Handle one-time schedules
                    elif not schedule.get('is_recurring', False):
                        # Check if this schedule hasn't been executed today
                        executed_dates = schedule.get('executed_dates', [])
                        if today_str not in executed_dates:
                            due_schedule = schedule.copy()
                            due_schedule['user_id'] = user_id
                            due_schedules.append(due_schedule)
                            
                            # Mark as executed today and deactivate
                            executed_dates.append(today_str)
                            schedule['executed_dates'] = executed_dates
                            schedule['active'] = False
                            schedules_to_deactivate.append((user_id, i))
            
            # Save changes for one-time schedules
            if schedules_to_deactivate:
                self.save_schedules()
            
            return due_schedules
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about schedules"""
        with self.lock:
            total_users = len(self.schedules)
            total_schedules = sum(
                len([s for s in user_schedules if s['active']]) 
                for user_schedules in self.schedules.values()
            )
            
            return {
                'total_users': total_users,
                'total_schedules': total_schedules,
                'max_per_user': self.max_schedules_per_user
            }