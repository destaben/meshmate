import json
import time
import io
import tarfile
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
import requests

from .base_handler import BaseHandler


class MeteoHandler(BaseHandler):
    """Handler for /meteo command"""
    
    def __init__(self, api_key: str, channel=None):
        super().__init__(command='meteo', channel=channel)
        self.aemet_api_key = api_key
        self.aemet_warnings_url = f"https://opendata.aemet.es/opendata/api/avisos_cap/ultimoelaborado/area/esp?api_key={api_key}"
    
    def handle(self, packet: Dict[str, Any], interface, log_json) -> Optional[str]:
        """
        Handle meteo command and send weather warnings from AEMET
        """
        try:
            info = self.extract_packet_info(packet)
            
            # Log meteo command received
            log_json("info", "Meteo command received",
                event_type="meteo_command_received",
                sender_id=info['sender_id'],
                channel=info['channel'],
                command_text=info['message_text']
            )
            
            # Get weather warnings
            warnings = self._get_weather_warnings(log_json)
            
            # Check if there was a timeout (None returned)
            if warnings is None:
                log_json("warning", "AEMET API timeout - no response sent",
                    event_type="aemet_timeout",
                    sender_id=info['sender_id'],
                    channel=info['channel']
                )
                return
            
            # Get response cards (one per phenomenon type)
            response_cards = self._format_warnings_response(warnings)
            
            # Send each alert card separately (no @ mention)
            total_cards_sent = 0
            for i, card in enumerate(response_cards):
                # Split card if it exceeds Meshtastic limits
                card_messages = self._split_message(card, max_length=200)
                
                for j, msg in enumerate(card_messages):
                    interface.sendText(msg, channelIndex=info['channel'])
                    total_cards_sent += 1
                    
                    # Small delay between messages to avoid flooding
                    if j < len(card_messages) - 1:
                        time.sleep(1)
                
                # Longer delay between different phenomena cards
                if i < len(response_cards) - 1:
                    time.sleep(2)
            
            # Log successful response
            log_json("info", "Meteo response sent",
                event_type="meteo_response_sent",
                response_cards=len(response_cards),
                total_messages=total_cards_sent,
                warnings_found=len(warnings),
                sender_id=info['sender_id'],
                original_message_id=info['message_id'],
                channel=info['channel']
            )
            
        except Exception as e:
            # Log error and send error message
            log_json("error", "Error in meteo handler",
                error=str(e),
                sender_id=info.get('sender_id', 'unknown'),
                original_message_id=info.get('message_id', 'unknown'),
                channel=info.get('channel', 'unknown')
            )
            
            error_msg = "❌ Error obteniendo datos meteorológicos"
            error_response = self.mention_user(info.get('sender_id', ''), error_msg)
            interface.sendText(error_response, channelIndex=info.get('channel', 0))
    
    def _get_weather_warnings(self, log_json) -> List[Dict[str, Any]]:
        """Get current weather warnings from AEMET API with retry logic"""
        import time
        
        warnings = []
        max_retries = 3
        retry_delay = 5  # seconds
        
        for attempt in range(max_retries):
            try:
                # First, get the data URL from AEMET API
                response = requests.get(self.aemet_warnings_url, timeout=30)
                
                log_json("info", "AEMET API request",
                    event_type="aemet_api_request",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    status_code=response.status_code
                )
                
                if response.status_code == 200:
                    api_response = response.json()
                    
                    # Check if the response is successful
                    if api_response.get('estado') == 200 and api_response.get('descripcion') == 'exito':
                        data_url = api_response.get('datos', '')
                        
                        if data_url:
                            # Now get the actual CAP warnings data
                            data_response = requests.get(data_url, timeout=30)
                            
                            if data_response.status_code == 200:
                                content_type = data_response.headers.get('content-type', '')
                                file_size = len(data_response.content)
                                
                                # Check if it's gzip (1f8b) or plain tar
                                if data_response.content.startswith(b'\x1f\x8b'):
                                    warnings = self._parse_tar_warnings(data_response.content, compressed=True, log_json=log_json)
                                    
                                    log_json("info", "AEMET data processed successfully",
                                        event_type="aemet_data_processed",
                                        format="gzip",
                                        file_size=file_size,
                                        warnings_found=len(warnings)
                                    )
                                    return warnings
                                    
                                elif 'tar' in content_type.lower() or 'gtar' in content_type.lower() or self._looks_like_tar(data_response.content):
                                    warnings = self._parse_tar_warnings(data_response.content, compressed=False, log_json=log_json)
                                    
                                    log_json("info", "AEMET data processed successfully",
                                        event_type="aemet_data_processed",
                                        format="tar",
                                        file_size=file_size,
                                        warnings_found=len(warnings)
                                    )
                                    return warnings
                                else:
                                    log_json("error", "Invalid AEMET data format",
                                        event_type="aemet_invalid_format",
                                        content_type=content_type,
                                        file_size=file_size
                                    )
                            else:
                                log_json("error", "Failed to download AEMET data",
                                    event_type="aemet_download_failed",
                                    status_code=data_response.status_code
                                )
                        else:
                            log_json("error", "No data URL in AEMET response",
                                event_type="aemet_no_data_url"
                            )
                    else:
                        log_json("error", "AEMET API error response",
                            event_type="aemet_api_error",
                            estado=api_response.get('estado'),
                            descripcion=api_response.get('descripcion')
                        )
                else:
                    log_json("error", "AEMET API request failed",
                        event_type="aemet_request_failed",
                        status_code=response.status_code
                    )
                
            except requests.exceptions.Timeout:
                log_json("warning", "AEMET API timeout",
                    event_type="aemet_timeout",
                    attempt=attempt + 1,
                    max_retries=max_retries
                )
                
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    return None  # Return None to indicate timeout failure
                    
            except Exception as e:
                log_json("error", "AEMET API exception",
                    event_type="aemet_exception",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e)
                )
                
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    break
        
        return warnings
    
    def _parse_tar_warnings(self, tar_content: bytes, compressed: bool = True, log_json=None) -> List[Dict[str, Any]]:
        """Parse tar or tar.gz file containing multiple CAP XML files"""
        all_warnings = []
        
        try:
            mode = 'r:gz' if compressed else 'r'
            
            # Create a file-like object from the bytes
            tar_file_obj = io.BytesIO(tar_content)
            
            # Open the tar file
            with tarfile.open(fileobj=tar_file_obj, mode=mode) as tar:
                members = tar.getmembers()
                xml_files = [m for m in members if m.isfile() and m.name.endswith('.xml')]
                
                if log_json:
                    log_json("info", "Processing AEMET archive",
                        event_type="aemet_archive_processing",
                        archive_type="gzip" if compressed else "tar",
                        total_files=len(members),
                        xml_files=len(xml_files)
                    )
                
                # Process each XML file
                for member in xml_files:
                    xml_file = tar.extractfile(member)
                    if xml_file:
                        try:
                            xml_content = xml_file.read().decode('utf-8')
                            warnings = self._parse_cap_xml(xml_content)
                            all_warnings.extend(warnings)
                        except Exception as e:
                            if log_json:
                                log_json("warning", "Failed to parse XML file",
                                    event_type="aemet_xml_parse_error",
                                    filename=member.name,
                                    error=str(e)
                                )
                
                if log_json:
                    log_json("info", "AEMET archive processed",
                        event_type="aemet_archive_processed",
                        xml_files_processed=len(xml_files),
                        total_warnings=len(all_warnings)
                    )
                            
        except Exception as e:
            if log_json:
                log_json("error", "TAR archive processing failed",
                    event_type="aemet_tar_error",
                    error=str(e)
                )
            
        return all_warnings
    
    def _looks_like_tar(self, content: bytes) -> bool:
        """Check if content looks like a TAR file by examining structure"""
        try:
            if len(content) < 512:
                return False
            
            # Try to peek into it as tar
            tar_file_obj = io.BytesIO(content)
            with tarfile.open(fileobj=tar_file_obj, mode='r') as tar:
                members = tar.getmembers()
                return len(members) > 0
        except Exception:
            return False
    
    def _parse_cap_xml(self, xml_content: str) -> List[Dict[str, Any]]:
        """Parse CAP XML format warnings from AEMET"""
        warnings = []
        
        try:
            root = ET.fromstring(xml_content)
            
            # CAP XML namespace
            namespaces = {
                'cap': 'urn:oasis:names:tc:emergency:cap:1.2'
            }
            
            # Find all alert info elements (only Spanish language)
            info_elements = root.findall('.//cap:info', namespaces)
            
            for info in info_elements:
                language = self._get_xml_text(info.find('cap:language', namespaces), '')
                
                # Only process Spanish alerts to avoid duplicates
                if language != 'es-ES':
                    continue
                
                # Extract warning information
                event = self._get_xml_text(info.find('cap:event', namespaces), 'Aviso meteorológico')
                severity = self._get_xml_text(info.find('cap:severity', namespaces), 'Desconocida')
                
                # Extract AEMET-specific parameters
                nivel = ''
                probabilidad = ''
                for param in info.findall('cap:parameter', namespaces):
                    value_name = self._get_xml_text(param.find('cap:valueName', namespaces), '')
                    value = self._get_xml_text(param.find('cap:value', namespaces), '')
                    
                    if 'nivel' in value_name.lower():
                        nivel = value
                    elif 'probabilidad' in value_name.lower():
                        probabilidad = value
                
                # Extract area information
                areas = []
                area_elements = info.findall('cap:area', namespaces)
                
                for area in area_elements:
                    area_desc = self._get_xml_text(area.find('cap:areaDesc', namespaces), 'Desconocida')
                    areas.append(area_desc)
                
                warning = {
                    'event': event,
                    'severity': severity,
                    'nivel': nivel,
                    'probabilidad': probabilidad,
                    'areas': areas
                }
                
                warnings.append(warning)
                
        except Exception as e:
            # Silently ignore XML parsing errors - some files may be malformed
            pass
            
        return warnings
    
    def _get_xml_text(self, element, default: str = '') -> str:
        """Helper to safely extract text from XML element"""
        return element.text.strip() if element is not None and element.text else default
    
    def _format_warnings_response(self, warnings: List[Dict[str, Any]]) -> List[str]:
        """Format warnings into readable response messages - RED ALERTS ONLY
        Returns list of messages (one per phenomenon if needed to stay under 200 chars)"""
        if not warnings:
            return ["✅ Sin avisos ROJOS activos en España.\n📡 AEMET"]
        
        # Filter for RED alerts only (Rojo/Red level)
        red_warnings = []
        for warning in warnings:
            nivel = warning.get('nivel', '').lower()
            severity = warning.get('severity', '').lower()
            
            # Check for red/rojo indicators
            if ('rojo' in nivel or 'red' in nivel or 
                'rojo' in severity or 'extreme' in severity):
                red_warnings.append(warning)
        
        if not red_warnings:
            return ["✅ Sin avisos ROJOS activos.\n📡 AEMET"]
        
        # Group red warnings by phenomenon 
        warning_groups = {}
        for warning in red_warnings:
            event = warning['event']
            phenomenon = self._extract_phenomenon(event.lower())
            
            if phenomenon not in warning_groups:
                warning_groups[phenomenon] = set()
            
            # Add all areas for this phenomenon (clean names first to avoid duplicates)
            for area in warning.get('areas', []):
                clean_area = self._clean_area_name(area)
                if clean_area:  # Only add non-empty clean names
                    warning_groups[phenomenon].add(clean_area)
        
        # Create individual cards for each phenomenon
        response_cards = []
        
        for phenomenon, areas_set in warning_groups.items():
            # Areas are already cleaned and deduplicated
            clean_areas = sorted(list(areas_set))
            
            short_phenomenon = self._get_short_phenomenon(phenomenon)
            
            # Try to fit ALL provinces in one card (max ~180 chars for content)
            base_card = f"🔴 ALERTA ROJA {short_phenomenon.upper()}:\n"
            footer = "\n📡 AEMET"
            available_space = 180 - len(base_card) - len(footer)
            
            # Build the province list trying to show ALL
            all_provinces_text = ", ".join(clean_areas)
            
            if len(all_provinces_text) <= available_space:
                # All provinces fit!
                card_content = base_card + all_provinces_text + footer
                response_cards.append(card_content)
            else:
                # Too many provinces, show as many as possible
                fitting_provinces = []
                current_length = 0
                
                for province in clean_areas:
                    test_length = current_length + len(province) + (2 if fitting_provinces else 0)  # +2 for ", "
                    
                    if test_length <= available_space:
                        fitting_provinces.append(province)
                        current_length = test_length
                    else:
                        break
                
                if fitting_provinces:
                    remaining_count = len(clean_areas) - len(fitting_provinces)
                    if remaining_count > 0:
                        provinces_text = f"{', '.join(fitting_provinces)} +{remaining_count}"
                    else:
                        provinces_text = ', '.join(fitting_provinces)
                else:
                    # Fallback: at least show first province + count
                    provinces_text = f"{clean_areas[0]} +{len(clean_areas)-1}"
                
                card_content = base_card + provinces_text + footer
                response_cards.append(card_content)
        
        return response_cards
    
    def _get_short_phenomenon(self, phenomenon: str) -> str:
        """Get phenomenon name for display (now returns full names)"""
        # Return the phenomenon name as-is (full names instead of abbreviations)
        return phenomenon.title()
    
    def _clean_area_name(self, area: str) -> str:
        """Extract province names from area descriptions"""
        # Spanish provinces and autonomous communities to look for
        spanish_provinces = [
            # Andalucía
            'Almería', 'Cádiz', 'Córdoba', 'Granada', 'Huelva', 'Jaén', 'Málaga', 'Sevilla',
            # Aragón
            'Huesca', 'Teruel', 'Zaragoza',
            # Asturias
            'Asturias',
            # Baleares
            'Baleares', 'Islas Baleares', 'Mallorca', 'Menorca', 'Ibiza', 'Formentera',
            # Canarias
            'Las Palmas', 'Santa Cruz de Tenerife', 'Tenerife', 'Gran Canaria', 'Lanzarote', 'Fuerteventura',
            # Cantabria
            'Cantabria',
            # Castilla-La Mancha
            'Albacete', 'Ciudad Real', 'Cuenca', 'Guadalajara', 'Toledo',
            # Castilla y León
            'Ávila', 'Burgos', 'León', 'Palencia', 'Salamanca', 'Segovia', 'Soria', 'Valladolid', 'Zamora',
            # Cataluña
            'Barcelona', 'Girona', 'Lleida', 'Tarragona',
            # Extremadura
            'Badajoz', 'Cáceres',
            # Galicia
            'A Coruña', 'Lugo', 'Ourense', 'Pontevedra',
            # La Rioja
            'La Rioja',
            # Madrid
            'Madrid',
            # Murcia
            'Murcia',
            # Navarra
            'Navarra',
            # País Vasco
            'Álava', 'Araba', 'Gipuzkoa', 'Guipúzcoa', 'Bizkaia', 'Vizcaya',
            # Comunidad Valenciana
            'Alicante', 'Castellón', 'Valencia',
            # Ceuta y Melilla
            'Ceuta', 'Melilla'
        ]
        
        # Look for any province name in the area string (case insensitive)
        area_lower = area.lower()
        for province in spanish_provinces:
            if province.lower() in area_lower:
                return province
        
        # If no known province found, return the original area
        return area
    
    def _extract_phenomenon(self, event_text: str) -> str:
        """Extract the main meteorological phenomenon from event text"""
        phenomena_map = {
            'tormenta': 'Tormentas',
            'lluvia': 'Lluvia',
            'nieve': 'Nieve',
            'viento': 'Viento',
            'temperatura': 'Temperatura',
            'calor': 'Calor',
            'frío': 'Frío',
            'costa': 'Costa',
            'niebla': 'Niebla',
            'hielo': 'Hielo'
        }
        
        for key, phenomenon in phenomena_map.items():
            if key in event_text:
                return phenomenon
                
        return 'Meteorológico'  # Default fallback
    
    def _split_message(self, message: str, max_length: int = 160) -> List[str]:
        """Split long messages into chunks that fit Meshtastic limits"""
        if len(message) <= max_length:
            return [message]
        
        parts = []
        lines = message.split('\n')
        current_part = ""
        
        for line in lines:
            test_part = current_part + ('\n' if current_part else '') + line
            
            if len(test_part) <= max_length:
                current_part = test_part
            else:
                if current_part:
                    parts.append(current_part)
                    current_part = line
                else:
                    # Single line too long, force split
                    parts.append(line[:max_length])
                    current_part = line[max_length:]
        
        if current_part:
            parts.append(current_part)
        
        return parts