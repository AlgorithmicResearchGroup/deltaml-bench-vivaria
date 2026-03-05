"""
Keygen.sh license validation for the Coding Agent
"""
import os
import sys
import requests
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from pathlib import Path
import hashlib
import platform
import socket

class LicenseValidator:
    """Validates licenses using Keygen.sh API"""
    
    # Cache license validation for 24 hours to avoid excessive API calls
    CACHE_DURATION = 86400  # seconds (24 hours)
    CACHE_FILE = "/tmp/.coding_agent_license_cache"
    
    def __init__(self):
        # Get from environment variables
        self.license_key = os.getenv("LICENSE_KEY", "").strip()
        self.keygen_account_id = os.getenv("KEYGEN_ACCOUNT_ID", "").strip()
        self.keygen_product_token = os.getenv("KEYGEN_PRODUCT_TOKEN", "").strip()
        
        # Generate a machine fingerprint if not provided
        self.fingerprint = os.getenv("FINGERPRINT") or self._generate_fingerprint()
        
        # API endpoint
        self.api_url = f"https://api.keygen.sh/v1/accounts/{self.keygen_account_id}"
        
    def _generate_fingerprint(self) -> str:
        """Generate a unique machine fingerprint"""
        # Combine hostname, platform, and MAC address for uniqueness
        hostname = socket.gethostname()
        platform_info = platform.platform()
        
        # Try to get MAC address
        try:
            import uuid
            mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff) 
                          for elements in range(0,2*6,2)][::-1])
        except:
            mac = "unknown"
        
        fingerprint_data = f"{hostname}-{platform_info}-{mac}"
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:32]
    
    def _read_cache(self) -> Optional[Dict]:
        """Read cached license validation result"""
        try:
            if os.path.exists(self.CACHE_FILE):
                with open(self.CACHE_FILE, 'r') as f:
                    cache_data = json.load(f)
                    
                # Check if cache is still valid
                cached_time = cache_data.get('timestamp', 0)
                if time.time() - cached_time < self.CACHE_DURATION:
                    return cache_data
        except:
            pass
        return None
    
    def _write_cache(self, data: Dict):
        """Write license validation result to cache"""
        try:
            cache_data = {
                **data,
                'timestamp': time.time()
            }
            Path(self.CACHE_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(self.CACHE_FILE, 'w') as f:
                json.dump(cache_data, f)
        except:
            pass  # Cache write failures are non-critical
    
    def validate(self, _recursion_depth=0) -> Tuple[bool, Dict]:
        """
        Validate the license key
        Returns: (is_valid, license_info)
        """
        # Skip validation in CI/CD environments
        if os.environ.get('CI') == 'true' or os.environ.get('SKIP_LICENSE_CHECK') == 'true':
            return True, {
                'valid': True,
                'status': 'skipped',
                'name': 'CI/CD Mode',
                'detail': 'License validation skipped in CI environment'
            }
            
        # Prevent infinite recursion
        if _recursion_depth > 3:
            return False, {
                'error': 'License validation failed after multiple attempts',
                'message': 'Please contact support'
            }
            
        # Check for required configuration
        if not all([self.license_key, self.keygen_account_id, self.keygen_product_token]):
            return False, {
                'error': 'Missing license configuration',
                'message': 'Please set LICENSE_KEY, KEYGEN_ACCOUNT_ID, and KEYGEN_PRODUCT_TOKEN environment variables'
            }
        
        # Check cache first
        cached_result = self._read_cache()
        if cached_result and cached_result.get('valid'):
            return True, cached_result
        
        try:
            # Validate license with Keygen.sh
            response = requests.post(
                f"{self.api_url}/licenses/actions/validate-key",
                headers={
                    "Authorization": f"Bearer {self.keygen_product_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                json={
                    "meta": {
                        "key": self.license_key,
                        "scope": {"fingerprint": self.fingerprint}
                    }
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                license_data = data.get('data', {})
                meta = data.get('meta', {})
                
                # Extract license information
                license_info = {
                    'valid': meta.get('valid', False),
                    'status': meta.get('status', 'unknown'),
                    'detail': meta.get('detail', ''),
                    'code': meta.get('code', ''),
                    'license_id': license_data.get('id', ''),
                    'name': license_data.get('attributes', {}).get('name', ''),
                    'expiry': license_data.get('attributes', {}).get('expiry'),
                    'uses': license_data.get('attributes', {}).get('uses'),
                    'max_uses': license_data.get('attributes', {}).get('maxUses'),
                    'fingerprint': self.fingerprint
                }
                
                # Handle OVERDUE status - try to heartbeat existing machine first
                if license_info['code'] == 'OVERDUE' and license_info.get('license_id'):
                    print("⏰ License is overdue for check-in...")
                    
                    # First, check if a machine exists for this fingerprint
                    list_response = requests.get(
                        f"{self.api_url}/machines",
                        headers={
                            "Authorization": f"Bearer {self.keygen_product_token}",
                            "Accept": "application/vnd.api+json"
                        },
                        timeout=10
                    )
                    
                    machine_exists = False
                    machine_id = None
                    
                    if list_response.status_code == 200:
                        machines = list_response.json().get('data', [])
                        for machine in machines:
                            if machine.get('attributes', {}).get('fingerprint') == self.fingerprint:
                                machine_exists = True
                                machine_id = machine.get('id')
                                break
                    
                    if machine_exists and machine_id:
                        # Machine exists, perform heartbeat
                        print(f"🔄 Performing heartbeat for existing machine...")
                        heartbeat_response = requests.post(
                            f"{self.api_url}/machines/{machine_id}/actions/ping",
                            headers={
                                "Authorization": f"Bearer {self.keygen_product_token}",
                                "Accept": "application/vnd.api+json"
                            },
                            timeout=10
                        )
                        
                        if heartbeat_response.status_code == 200:
                            print("✅ Heartbeat successful")
                            # Clear cache and re-validate
                            try:
                                os.remove(self.CACHE_FILE)
                            except:
                                pass
                            return self.validate(_recursion_depth=_recursion_depth + 1)
                        else:
                            print(f"❌ Heartbeat failed: {heartbeat_response.status_code}")
                    else:
                        # No machine exists, create one
                        print("📱 Creating new machine...")
                        machine_response = requests.post(
                            f"{self.api_url}/machines",
                            headers={
                                "Authorization": f"Bearer {self.keygen_product_token}",
                                "Content-Type": "application/vnd.api+json",
                                "Accept": "application/vnd.api+json"
                            },
                            json={
                                "data": {
                                    "type": "machines",
                                    "attributes": {
                                        "fingerprint": self.fingerprint,
                                        "platform": platform.system().lower(),
                                        "hostname": socket.gethostname(),
                                        "cores": os.cpu_count() or 1
                                    },
                                    "relationships": {
                                        "license": {
                                            "data": {
                                                "type": "licenses",
                                                "id": license_info['license_id']
                                            }
                                        }
                                    }
                                }
                            },
                            timeout=10
                        )
                        
                        if machine_response.status_code == 201:
                            print("✅ Machine created successfully")
                            # Clear cache and re-validate
                            try:
                                os.remove(self.CACHE_FILE)
                            except:
                                pass
                            return self.validate(_recursion_depth=_recursion_depth + 1)
                        elif machine_response.status_code == 422 and "MACHINE_LIMIT_EXCEEDED" in machine_response.text:
                            print("❌ Machine limit exceeded - please deactivate an existing machine")
                            license_info['detail'] = "Machine limit exceeded for license"
                        else:
                            print(f"❌ Failed to create machine: {machine_response.status_code}")
                
                # Cache successful validation
                if license_info['valid']:
                    self._write_cache(license_info)
                
                return license_info['valid'], license_info
            
            elif response.status_code == 404:
                return False, {
                    'valid': False,
                    'error': 'License not found',
                    'message': 'The provided license key does not exist'
                }
            
            else:
                return False, {
                    'valid': False,
                    'error': f'API error: {response.status_code}',
                    'message': response.text
                }
                
        except requests.exceptions.Timeout:
            # If we can't reach the license server, check cache
            if cached_result:
                print("⚠️  License server timeout, using cached validation")
                return cached_result.get('valid', False), cached_result
            
            return False, {
                'valid': False,
                'error': 'License server timeout',
                'message': 'Could not reach license server. Please check your internet connection.'
            }
            
        except Exception as e:
            return False, {
                'valid': False,
                'error': f'Validation error: {str(e)}',
                'message': 'An error occurred during license validation'
            }
    
    def enforce(self, mode: str = "agent"):
        """
        Enforce license validation and exit if invalid
        mode: 'agent' or 'web' for different messaging
        """
        print("=" * 60)
        print("🚀 Coding Agent - License Validation")
        print("=" * 60)
        
        is_valid, info = self.validate()
        
        if is_valid:
            print(f"✅ License validated successfully")
            if info.get('name'):
                print(f"📝 License: {info['name']}")
            if info.get('expiry'):
                print(f"📅 Expires: {info['expiry']}")
            if info.get('uses') is not None and info.get('max_uses'):
                print(f"🔢 Uses: {info['uses']}/{info['max_uses']}")
            print(f"🔐 Machine ID: {self.fingerprint[:8]}...")
        else:
            print(f"❌ License validation failed")
            print(f"📛 {info.get('error', 'Unknown error')}")
            print(f"💬 {info.get('message', '')}")
            
            if mode == "web":
                print("\n🌐 The web interface requires a valid license.")
            else:
                print("\n🤖 The agent requires a valid license.")
            
            print("\n📧 Contact info@algorithicresearchgroup.com for assistance")
            print("🛒 Purchase a license at https://prospectml.com/pricing")
        
        print("=" * 60)
        
        if not is_valid:
            sys.exit(1)
        
        return info
    
    @classmethod
    def get_status(cls) -> Dict:
        """Get current license status for display in UI"""
        validator = cls()
        is_valid, info = validator.validate()
        
        if is_valid:
            status = {
                'valid': True,
                'type': 'licensed',
                'name': info.get('name', 'Unknown'),
                'expiry': info.get('expiry'),
                'fingerprint': validator.fingerprint[:8] + '...'
            }
            
            # Check if expiring soon
            if info.get('expiry'):
                try:
                    expiry_date = datetime.fromisoformat(info['expiry'].replace('Z', '+00:00'))
                    days_until_expiry = (expiry_date - datetime.now()).days
                    status['days_until_expiry'] = days_until_expiry
                    status['expiring_soon'] = days_until_expiry <= 30
                except:
                    pass
                    
            return status
        else:
            return {
                'valid': False,
                'type': 'invalid',
                'error': info.get('error', 'Unknown error'),
                'message': info.get('message', '')
            }


# Convenience function for quick validation
def validate_license() -> bool:
    """Simple boolean check for license validity"""
    validator = LicenseValidator()
    is_valid, _ = validator.validate()
    return is_valid


# Convenience function for enforcing license
def enforce_license(mode: str = "agent"):
    """Enforce license and exit if invalid"""
    validator = LicenseValidator()
    validator.enforce(mode)