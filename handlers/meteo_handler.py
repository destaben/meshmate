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
            print(f"\n🌦️ METEO Command received from {info['sender_id']} on channel {info['channel']}")
            print(f"📝 Message: '{info['message_text']}'")
            print("🔴 NOTE: Only RED (extreme) weather alerts will be shown")
            
            # Get weather warnings
            print("🔍 Starting weather warnings retrieval...")
            warnings = self._get_weather_warnings()
            
            # Check if there was a timeout (None returned)
            if warnings is None:
                print("⏰ Timeout occurred, not sending any message to avoid spam")
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
    
    def _get_weather_warnings(self) -> List[Dict[str, Any]]:
        """Get current weather warnings from AEMET API with retry logic"""
        import time
        
        warnings = []
        max_retries = 3
        retry_delay = 5  # seconds
        
        for attempt in range(max_retries):
            try:
                print(f"🌐 Requesting AEMET API (attempt {attempt + 1}/{max_retries}): {self.aemet_warnings_url[:80]}...")
                
                # First, get the data URL from AEMET API
                response = requests.get(self.aemet_warnings_url, timeout=30)  # Increased timeout
                print(f"📡 AEMET API response: {response.status_code}")
                
                if response.status_code == 200:
                    api_response = response.json()
                    print(f"✅ API Response: estado={api_response.get('estado')}, descripcion='{api_response.get('descripcion')}'")
                    
                    # Check if the response is successful
                    if api_response.get('estado') == 200 and api_response.get('descripcion') == 'exito':
                        data_url = api_response.get('datos', '')
                        print(f"📂 Data URL obtained: {data_url}")
                        
                        if data_url:
                            print("⬇️ Downloading data file...")
                            # Now get the actual CAP warnings data
                            data_response = requests.get(data_url, timeout=30)  # Increased timeout
                            print(f"📦 Download response: {data_response.status_code}, size: {len(data_response.content)} bytes")
                            
                            if data_response.status_code == 200:
                                # Check if content is actually a tar.gz file or JSON error
                                content_type = data_response.headers.get('content-type', '')
                                print(f"📋 Content-Type: {content_type}")
                                
                                # Check first few bytes to identify file type
                                first_bytes = data_response.content[:10]
                                print(f"🔍 First bytes: {first_bytes.hex()}")
                                
                                # Check if it's gzip (1f8b) or plain tar
                                if data_response.content.startswith(b'\x1f\x8b'):
                                    print("✅ Valid gzip file detected")
                                    warnings = self._parse_tar_warnings(data_response.content, compressed=True)
                                    print(f"⚠️ Found {len(warnings)} warnings")
                                    return warnings  # Success! Return immediately
                                elif 'tar' in content_type.lower() or 'gtar' in content_type.lower() or self._looks_like_tar(data_response.content):
                                    print("✅ Plain TAR file detected")
                                    warnings = self._parse_tar_warnings(data_response.content, compressed=False)
                                    print(f"⚠️ Found {len(warnings)} warnings")
                                    return warnings  # Success! Return immediately
                                else:
                                    print("❌ Response is neither gzip nor tar file")
                                    # Try to parse as JSON to see if it's an error response
                                    try:
                                        error_response = data_response.json()
                                        print(f"📄 JSON response: {error_response}")
                                    except:
                                        print(f"📄 Raw response (first 200 chars): {data_response.text[:200]}")
                            else:
                                print(f"❌ Failed to download data file: {data_response.status_code}")
                        else:
                            print("❌ No data URL in response")
                    else:
                        print(f"❌ API error: {api_response}")
                else:
                    print(f"❌ API request failed: {response.status_code}")
                
            except requests.exceptions.Timeout:
                print(f"⏰ Timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    print(f"⏳ Waiting {retry_delay} seconds before retry...")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"💥 All {max_retries} attempts failed due to timeout")
                    return None  # Return None to indicate timeout failure
                    
            except Exception as e:
                print(f"💥 Exception on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    print(f"⏳ Waiting {retry_delay} seconds before retry...")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"💥 All {max_retries} attempts failed")
        
        print(f"🔄 Returning {len(warnings)} warnings after all retries")
        return warnings
    
    def _parse_tar_warnings(self, tar_content: bytes, compressed: bool = True) -> List[Dict[str, Any]]:
        """Parse tar or tar.gz file containing multiple CAP XML files"""
        all_warnings = []
        
        try:
            if compressed:
                print(f"📁 Attempting to open compressed tar.gz archive...")
                # Validate gzip header
                if not tar_content.startswith(b'\x1f\x8b'):
                    print(f"❌ Invalid gzip header. First 20 bytes: {tar_content[:20].hex()}")
                    return []
                mode = 'r:gz'
            else:
                print(f"📁 Attempting to open plain tar archive...")
                mode = 'r'
            
            # Create a file-like object from the bytes
            tar_file_obj = io.BytesIO(tar_content)
            
            # Open the tar file
            with tarfile.open(fileobj=tar_file_obj, mode=mode) as tar:
                members = tar.getmembers()
                print(f"📋 Archive contains {len(members)} files")
                
                # List all files for debugging
                for member in members:
                    print(f"   📄 File: {member.name} ({member.size} bytes, {'file' if member.isfile() else 'directory'})")
                
                # Process each file in the tar (limit logging for performance)
                xml_count = 0
                processed_warnings = 0
                
                for member in tar.getmembers():
                    if member.isfile() and member.name.endswith('.xml'):
                        xml_count += 1
                        
                        # Log every 50th file to avoid spam
                        if xml_count % 50 == 1 or xml_count <= 5:
                            print(f"🔍 Processing XML {xml_count}: {member.name}")
                        
                        # Extract and read the XML file
                        xml_file = tar.extractfile(member)
                        if xml_file:
                            try:
                                xml_content = xml_file.read().decode('utf-8')
                                # Only verbose parsing for first few files
                                verbose_mode = (xml_count <= 3)
                                warnings = self._parse_cap_xml(xml_content, verbose=verbose_mode)
                                file_warning_count = len(warnings)
                                all_warnings.extend(warnings)
                                processed_warnings += file_warning_count
                                
                                # Log details for first few files or when warnings found
                                if xml_count <= 5 or file_warning_count > 0:
                                    print(f"   └─ Found {file_warning_count} warnings")
                                    
                            except UnicodeDecodeError as ude:
                                if xml_count <= 5:
                                    print(f"   └─ ❌ Unicode decode error: {str(ude)}")
                            except Exception as xe:
                                if xml_count <= 5:
                                    print(f"   └─ ❌ XML parsing error: {str(xe)}")
                        else:
                            if xml_count <= 5:
                                print(f"   └─ ❌ Could not extract file")
                
                print(f"📊 Processed {xml_count} XML files, total warnings: {len(all_warnings)}")
                if xml_count > 10:
                    print(f"📝 (Detailed logging shown for first 5 files only)")
                            
        except tarfile.TarError as te:
            print(f"💥 Tar file error: {str(te)}")
        except Exception as e:
            print(f"💥 Exception in _parse_tar_warnings: {str(e)}")
            
        return all_warnings
    
    def _looks_like_tar(self, content: bytes) -> bool:
        """Check if content looks like a TAR file by examining structure"""
        try:
            # TAR files have a specific header structure
            # Check if we can at least identify it as a potential tar
            if len(content) < 512:
                return False
            
            # Check for typical TAR file patterns
            # TAR files often start with filename patterns
            first_block = content[:512].decode('ascii', errors='ignore')
            
            # Look for common CAP file patterns in AEMET
            if any(pattern in first_block for pattern in ['CAP', '.xml', 'LEMM', 'AFAZ']):
                print(f"   🎯 TAR pattern detected: {first_block[:50]}")
                
            # Try to peek into it as tar
            tar_file_obj = io.BytesIO(content)
            with tarfile.open(fileobj=tar_file_obj, mode='r') as tar:
                # If we can list members without error, it's likely a tar
                members = tar.getmembers()
                print(f"   ✅ TAR validation: {len(members)} members found")
                return len(members) > 0
        except Exception as e:
            print(f"   ❌ TAR validation failed: {str(e)}")
            return False
    
    def _parse_cap_xml(self, xml_content: str, verbose: bool = False) -> List[Dict[str, Any]]:
        """Parse CAP XML format warnings from AEMET"""
        warnings = []
        
        try:
            if verbose:
                print(f"🔍 Parsing CAP XML content ({len(xml_content)} chars)...")
            
            root = ET.fromstring(xml_content)
            
            # CAP XML namespace
            namespaces = {
                'cap': 'urn:oasis:names:tc:emergency:cap:1.2'
            }
            
            # Find all alert info elements (only Spanish language)
            info_elements = root.findall('.//cap:info', namespaces)
            
            if verbose:
                print(f"📄 Found {len(info_elements)} info elements in XML")
            
            spanish_count = 0
            for info in info_elements:
                language = self._get_xml_text(info.find('cap:language', namespaces), '')
                
                # Only process Spanish alerts to avoid duplicates
                if language != 'es-ES':
                    if verbose:
                        print(f"   └─ Skipping language: {language}")
                    continue
                
                spanish_count += 1
                if verbose:
                    print(f"   ✅ Processing Spanish alert #{spanish_count}")
                    
                # Extract warning information
                event = self._get_xml_text(info.find('cap:event', namespaces), 'Aviso meteorológico')
                severity = self._get_xml_text(info.find('cap:severity', namespaces), 'Desconocida')
                
                if verbose:
                    print(f"      📋 Event: {event}, Severity: {severity}")
                
                # Extract AEMET-specific parameters
                nivel = ''
                probabilidad = ''
                param_count = 0
                for param in info.findall('cap:parameter', namespaces):
                    param_count += 1
                    value_name = self._get_xml_text(param.find('cap:valueName', namespaces), '')
                    value = self._get_xml_text(param.find('cap:value', namespaces), '')
                    
                    if 'nivel' in value_name.lower():
                        nivel = value
                    elif 'probabilidad' in value_name.lower():
                        probabilidad = value
                
                if verbose:
                    print(f"      🎯 Processed {param_count} parameters - Nivel: {nivel}, Probabilidad: {probabilidad}")
                
                # Extract area information
                areas = []
                area_elements = info.findall('cap:area', namespaces)
                
                if verbose:
                    print(f"      🗺️ Found {len(area_elements)} area elements")
                
                for area in area_elements:
                    area_desc = self._get_xml_text(area.find('cap:areaDesc', namespaces), 'Desconocida')
                    areas.append(area_desc)
                    if verbose:
                        print(f"         └─ Area: {area_desc}")
                
                warning = {
                    'event': event,
                    'severity': severity,
                    'nivel': nivel,
                    'probabilidad': probabilidad,
                    'areas': areas
                }
                
                warnings.append(warning)
                if verbose:
                    print(f"      ✅ Added warning for {len(areas)} areas")
                
        except Exception as e:
            if verbose:
                print(f"💥 Exception in _parse_cap_xml: {str(e)}")
            
        if verbose:
            print(f"🔄 Returning {len(warnings)} parsed warnings")
        return warnings
    
    def _get_xml_text(self, element, default: str = '') -> str:
        """Helper to safely extract text from XML element"""
        return element.text.strip() if element is not None and element.text else default
    
    def _format_warnings_response(self, warnings: List[Dict[str, Any]]) -> List[str]:
        """Format warnings into readable response messages - RED ALERTS ONLY
        Returns list of messages (one per phenomenon if needed to stay under 200 chars)"""
        if not warnings:
            print("📝 No warnings found, returning 'no alerts' message")
            return ["✅ Sin avisos ROJOS activos en España.\n📡 AEMET"]
        
        print(f"📝 Filtering {len(warnings)} warnings for RED alerts only...")
        
        # Filter for RED alerts only (Rojo/Red level)
        red_warnings = []
        for warning in warnings:
            nivel = warning.get('nivel', '').lower()
            severity = warning.get('severity', '').lower()
            
            # Check for red/rojo indicators
            if ('rojo' in nivel or 'red' in nivel or 
                'rojo' in severity or 'extreme' in severity):
                red_warnings.append(warning)
        
        print(f"🔴 Found {len(red_warnings)} RED alerts out of {len(warnings)} total")
        
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
        
        print(f"🔴 Grouped RED alerts: {list(warning_groups.keys())}")
        
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
                print(f"   🔴 Card for {short_phenomenon}: ALL {len(clean_areas)} provinces fit ({len(card_content)} chars)")
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
                print(f"   🔴 Card for {short_phenomenon}: {len(fitting_provinces)} of {len(clean_areas)} provinces ({len(card_content)} chars)")
        
        print(f"📨 Created {len(response_cards)} alert cards")
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