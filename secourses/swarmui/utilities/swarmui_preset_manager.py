#!/usr/bin/env python3
"""
SwarmUI Preset Manager using Built-in API

This script uses SwarmUI's built-in API to:
1. Backup existing presets
2. Delete all presets
3. Import new presets from JSON file

Requires SwarmUI to be running!
"""

import requests
import json
import os
import glob
from datetime import datetime

class SwarmUIPresetManager:
    def __init__(self, ports=[7861, 7862, 7860, 7800, 7801]):
        self.ports = ports
        self.base_url = None
        self.session_id = None
        self.active_port = None
        
    def discover_active_port(self):
        """Discover which port SwarmUI is running on"""
        print("DISCOVERING: Checking ports for SwarmUI...")
        
        for port in self.ports:
            test_url = f"http://localhost:{port}"
            try:
                headers = {'Content-Type': 'application/json'}
                response = requests.post(f"{test_url}/API/GetNewSession", 
                                       json={}, headers=headers, timeout=3)
                if response.status_code == 200:
                    data = response.json()
                    if 'session_id' in data:
                        self.base_url = test_url
                        self.active_port = port
                        self.session_id = data.get('session_id')
                        print(f"SUCCESS: Found SwarmUI on port {port}")
                        return True
                    else:
                        print(f"   Port {port}: Invalid response format")
                else:
                    print(f"   Port {port}: HTTP {response.status_code}")
            except requests.exceptions.ConnectionError as e:
                if "Connection refused" in str(e) or "10061" in str(e):
                    print(f"   Port {port}: Connection refused")
                else:
                    print(f"   Port {port}: Connection error: {e}")
            except requests.exceptions.Timeout:
                print(f"   Port {port}: Timeout")
            except Exception as e:
                print(f"   Port {port}: {type(e).__name__}: {e}")
        
        print("ERROR: No active SwarmUI instance found on any port")
        return False
    
    def get_session(self):
        """Get a new session ID from SwarmUI"""
        # If we don't have a base URL yet, discover it
        if not self.base_url:
            return self.discover_active_port()
        
        # If we already have a URL, try to get a session
        try:
            headers = {'Content-Type': 'application/json'}
            response = requests.post(f"{self.base_url}/API/GetNewSession", 
                                   json={}, headers=headers)
            if response.status_code == 200:
                data = response.json()
                self.session_id = data.get('session_id')
                return True
            return False
        except Exception as e:
            print(f"ERROR: Error connecting to SwarmUI on {self.base_url}: {e}")
            # Try to rediscover if connection failed
            self.base_url = None
            self.active_port = None
            return self.discover_active_port()
    
    def api_request(self, endpoint, data=None):
        """Make an API request to SwarmUI"""
        if not self.session_id:
            if not self.get_session():
                return None
        
        # SwarmUI expects JSON with proper headers
        headers = {'Content-Type': 'application/json'}
        payload = data or {}
        payload['session_id'] = self.session_id
        
        try:
            response = requests.post(f"{self.base_url}/API/{endpoint}", 
                                   json=payload, headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"ERROR: API Error: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"ERROR: Request error: {e}")
            return None
    
    def get_all_presets(self):
        """Get all user presets from SwarmUI"""
        data = self.api_request('GetMyUserData')
        if data and 'presets' in data:
            return data['presets']
        return []
    
    def backup_presets(self, backup_dir="presets_backups"):
        """Backup all presets to JSON file"""
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        presets = self.get_all_presets()
        if not presets:
            print("INFO: No presets found to backup")
            return None
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"presets_backup_{timestamp}.json")
        
        # Convert to the format expected by SwarmUI import
        backup_data = {}
        for preset in presets:
            backup_data[preset['title']] = preset
        
        try:
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, indent=4, ensure_ascii=False)
            
            print(f"SUCCESS: Backup created: {backup_file}")
            print(f"   Backed up {len(presets)} presets")
            return backup_file
        except Exception as e:
            print(f"ERROR: Failed to create backup: {e}")
            return None
    
    def delete_all_presets(self):
        """Delete all presets using SwarmUI API"""
        presets = self.get_all_presets()
        if not presets:
            print("INFO: No presets to delete")
            return True
        
        deleted_count = 0
        failed_count = 0
        
        print(f"DELETING: {len(presets)} presets...")
        
        for preset in presets:
            result = self.api_request('DeletePreset', {'preset': preset['title']})
            if result and result.get('success'):
                deleted_count += 1
                print(f"   SUCCESS: Deleted: {preset['title']}")
            else:
                failed_count += 1
                print(f"   ERROR: Failed to delete: {preset['title']}")
        
        print(f"COMPLETE: Deletion complete: {deleted_count} deleted, {failed_count} failed")
        return failed_count == 0
    
    def find_latest_preset_file(self):
        """Find the latest Amazing_SwarmUI_Presets_v*.json file"""
        # Look in current directory first
        pattern = "Amazing_SwarmUI_Presets_v*.json"
        files = glob.glob(pattern)
        
        # If not found, look in parent directory
        if not files:
            parent_pattern = os.path.join("..", "Amazing_SwarmUI_Presets_v*.json")
            files = glob.glob(parent_pattern)
        
        if not files:
            print("ERROR: No Amazing_SwarmUI_Presets_v*.json files found")
            print("   Searched in current directory and parent directory")
            return None
        
        # Extract version numbers and find the latest
        latest_version = 0
        latest_file = None
        
        for file in files:
            try:
                # Get just the filename without path for version extraction
                filename = os.path.basename(file)
                version_str = filename.replace("Amazing_SwarmUI_Presets_v", "").replace(".json", "")
                version = int(version_str)
                if version > latest_version:
                    latest_version = version
                    latest_file = file  # Keep the full path
            except ValueError:
                continue
        
        return latest_file
    
    def import_presets_from_file(self, file_path=None):
        """Import presets from JSON file using SwarmUI API"""
        if not file_path:
            file_path = self.find_latest_preset_file()
        
        if not file_path:
            return False
        
        if not os.path.exists(file_path):
            print(f"ERROR: File not found: {file_path}")
            return False
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            print(f"IMPORTING: Importing presets from: {os.path.abspath(file_path)}")
            
            # Handle different JSON structures
            if isinstance(data, list):
                presets_data = {f"preset_{i}": preset for i, preset in enumerate(data)}
            elif isinstance(data, dict) and all(isinstance(v, dict) and 'title' in v for v in data.values()):
                presets_data = data
            else:
                print("ERROR: Invalid preset file format")
                return False
            
            imported_count = 0
            failed_count = 0
            
            print(f"IMPORTING: {len(presets_data)} presets...")
            
            for key, preset in presets_data.items():
                # Prepare data for SwarmUI API - use direct param_map structure
                param_map = preset.get('param_map', {})
                import_data = {
                    'title': preset.get('title', key),
                    'description': preset.get('description', ''),
                    'param_map': param_map,  # Direct param_map field works
                    'preview_image': preset.get('preview_image', ''),
                    'is_edit': False
                }
                
                result = self.api_request('AddNewPreset', import_data)
                if result and not result.get('preset_fail'):
                    imported_count += 1
                    print(f"   SUCCESS: Imported: {preset.get('title', key)}")
                else:
                    failed_count += 1
                    error_msg = result.get('preset_fail', 'Unknown error') if result else 'API request failed'
                    print(f"   ERROR: Failed to import {preset.get('title', key)}: {error_msg}")
            
            print(f"COMPLETE: Import complete: {imported_count} imported, {failed_count} failed")
            return failed_count == 0
            
        except Exception as e:
            print(f"ERROR: Error importing presets: {e}")
            return False

def main():
    print("=" * 50)
    print("  SwarmUI Preset Manager")
    print("=" * 50)
    print()
    
    manager = SwarmUIPresetManager()
    
    # Check if SwarmUI is running
    print("CHECKING: Checking SwarmUI connection...")
    if not manager.get_session():
        print("ERROR: Cannot connect to SwarmUI!")
        print("   Make sure SwarmUI is running on one of these ports:")
        print("   - http://localhost:7861")
        print("   - http://localhost:7862") 
        print("   - http://localhost:7860")
        print("   - http://localhost:7800")
        print("   - http://localhost:7801")
        return False
    
    print(f"SUCCESS: Connected to SwarmUI on port {manager.active_port}")
    print()
    
    # Step 1: Backup existing presets
    print("STEP 1: Creating backup...")
    backup_file = manager.backup_presets()
    if not backup_file:
        print("WARNING: Backup failed, but continuing...")
    print()
    
    # Step 2: Delete all presets
    print("STEP 2: Deleting all existing presets...")
    if not manager.delete_all_presets():
        print("WARNING: Some presets failed to delete, but continuing...")
    print()
    
    # Step 3: Import new presets
    print("STEP 3: Importing new presets...")
    if manager.import_presets_from_file():
        print()
        print("SUCCESS: Preset management completed successfully!")
        print("REFRESH: Refresh your SwarmUI web interface to see the new presets.")
    else:
        print()
        print("ERROR: Import failed!")
        if backup_file:
            print(f"BACKUP: Your original presets are backed up in: {backup_file}")
    
    return True

if __name__ == "__main__":
    main()