"""
URL Downloader Module for SwarmUI Model Downloader
Supports CivitAI, HuggingFace, and generic URL downloads with robust parsing and filename handling.
"""

import os
import re
import requests
import urllib.parse
from typing import Optional, Tuple, Dict, Any
from pathlib import Path
import json
import time
from .HF_model_downloader import RobustDownloader, DEFAULT_DOWNLOAD_CONFIG

class URLDownloader:
    """
    Robust URL downloader that handles various URL formats and provides
    proper filename extraction and download functionality.
    """
    
    def __init__(self, config: Optional[Dict] = None, civitai_api_key: Optional[str] = None, huggingface_api_key: Optional[str] = None):
        """Initialize the URL downloader with configuration."""
        self.config = config or DEFAULT_DOWNLOAD_CONFIG
        self.civitai_api_key = civitai_api_key or "5577db242d28f46030f55164cdd2da5d"  # Default API key
        self.huggingface_api_key = huggingface_api_key  # Optional HF API key
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

        # IMPORTANT SECURITY NOTE:
        # We do NOT set the HuggingFace token as a global Session header, to avoid
        # leaking it to non-HuggingFace hosts (CivitAI, arbitrary URLs, etc).
        # Instead, we attach it per-request only for HuggingFace domains.

    def _is_huggingface_host(self, host: str | None) -> bool:
        if not host:
            return False
        host = host.lower()
        return (
            host == "huggingface.co"
            or host.endswith(".huggingface.co")
            or host == "hf.co"
            or host.endswith(".hf.co")
        )

    def _headers_with_optional_hf_auth(self, url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        merged: Dict[str, str] = dict(headers) if headers else {}
        token = self.huggingface_api_key
        if token:
            try:
                host = urllib.parse.urlparse(url).hostname
            except Exception:
                host = None
            if self._is_huggingface_host(host):
                merged.setdefault("Authorization", f"Bearer {token}")
        return merged

    def _request(self, method: str, url: str, *, headers: Optional[Dict[str, str]] = None, **kwargs):
        """
        Request helper that attaches HF auth only to HuggingFace hosts.
        If a token is rejected (401/403), retry once without token and disable it.
        """
        merged_headers = self._headers_with_optional_hf_auth(url, headers)
        resp = self.session.request(method, url, headers=merged_headers, **kwargs)

        if resp.status_code in (401, 403) and self.huggingface_api_key:
            try:
                host = urllib.parse.urlparse(url).hostname
            except Exception:
                host = None
            if self._is_huggingface_host(host):
                resp.close()
                # Disable token for subsequent URL requests
                self.huggingface_api_key = None
                retry_headers = dict(headers) if headers else {}
                retry_headers.pop("Authorization", None)
                return self.session.request(method, url, headers=retry_headers, **kwargs)

        return resp
        
    def parse_url(self, url: str) -> Dict[str, Any]:
        """
        Parse various URL formats and return standardized download information.
        
        Args:
            url: Input URL (CivitAI, HuggingFace, or generic)
            
        Returns:
            Dict containing:
            - download_url: The actual download URL
            - filename: Suggested filename
            - source_type: 'civitai', 'huggingface', or 'generic'
            - original_url: The original input URL
            - metadata: Additional metadata if available
        """
        url = url.strip()
        
        # CivitAI URL parsing
        if 'civitai.com' in url.lower():
            return self._parse_civitai_url(url)
        
        # HuggingFace URL parsing
        elif 'huggingface.co' in url.lower():
            return self._parse_huggingface_url(url)
        
        # Generic URL
        else:
            return self._parse_generic_url(url)
    
    def _parse_civitai_url(self, url: str) -> Dict[str, Any]:
        """
        Parse CivitAI URLs and convert to download API endpoints.
        
        Supported formats:
        - https://civitai.com/models/1940709/retro-anime?modelVersionId=2196504
        - https://civitai.com/models/302872/lizmix?modelVersionId=1451507
        """
        try:
            # Extract modelVersionId from URL
            version_match = re.search(r'modelVersionId=(\d+)', url)
            if not version_match:
                # Try to extract from path if not in query params
                path_match = re.search(r'/models/(\d+)', url)
                if path_match:
                    model_id = path_match.group(1)
                    # For direct model URLs without version, we'll need to fetch the latest version
                    return {
                        'download_url': f"https://civitai.com/api/download/models/{model_id}?type=Model&format=SafeTensor",
                        'filename': None,  # Will be determined from server response
                        'source_type': 'civitai',
                        'original_url': url,
                        'metadata': {'model_id': model_id, 'version_id': None}
                    }
                else:
                    raise ValueError("Could not extract model ID from CivitAI URL")
            
            version_id = version_match.group(1)
            
            # Build download URL with API key for authentication
            download_url = f"https://civitai.com/api/download/models/{version_id}?type=Model&format=SafeTensor&token={self.civitai_api_key}"
            
            # Note: We don't add size=pruned&fp=fp16 by default as many models only have full versions
            # The API will serve the available version automatically
            
            return {
                'download_url': download_url,
                'filename': None,  # Will be determined from server response
                'source_type': 'civitai',
                'original_url': url,
                'metadata': {'version_id': version_id}
            }
            
        except Exception as e:
            raise ValueError(f"Failed to parse CivitAI URL: {e}")
    
    
    def _parse_huggingface_url(self, url: str) -> Dict[str, Any]:
        """
        Parse HuggingFace URLs and extract download information.
        
        Supported formats:
        - https://huggingface.co/SG161222/RealVisXL_V5.0/resolve/main/RealVisXL_V5.0_fp16.safetensors?download=true
        - https://huggingface.co/SG161222/RealVisXL_V5.0/blob/main/RealVisXL_V5.0_fp16.safetensors
        """
        try:
            # Convert blob URLs to resolve URLs for direct download
            if '/blob/' in url:
                url = url.replace('/blob/', '/resolve/')
            
            # Add download=true parameter if not present
            if 'download=true' not in url and '?' not in url:
                url += '?download=true'
            elif 'download=true' not in url and '?' in url:
                url += '&download=true'
            
            # Extract filename from URL
            filename = None
            path_parts = urllib.parse.urlparse(url).path.split('/')
            
            # For HuggingFace URLs, the filename is typically the last part of the path
            # after /resolve/main/ or /blob/main/
            if len(path_parts) >= 2:
                # Find the index of 'main' or 'resolve'
                main_index = -1
                for i, part in enumerate(path_parts):
                    if part == 'main':
                        main_index = i
                        break
                
                # If we found 'main', the filename should be after it
                if main_index != -1 and main_index + 1 < len(path_parts):
                    # Join all parts after 'main' in case the filename has subdirectories
                    filename_parts = path_parts[main_index + 1:]
                    filename = '/'.join(filename_parts) if filename_parts else None
                    # If it's a single file (no subdirectories), just use the basename
                    if filename and '/' not in filename:
                        filename = os.path.basename(filename)
                    elif filename:
                        # For subdirectories, use the last part as filename
                        filename = os.path.basename(filename)
            
            if not filename:
                # Fallback: use the last part of the path
                filename = path_parts[-1] if path_parts[-1] else None
            
            # Extract repository info
            repo_match = re.search(r'huggingface\.co/([^/]+/[^/]+)', url)
            repo_id = repo_match.group(1) if repo_match else None
            
            return {
                'download_url': url,
                'filename': filename,
                'source_type': 'huggingface',
                'original_url': url,
                'metadata': {'repo_id': repo_id}
            }
            
        except Exception as e:
            raise ValueError(f"Failed to parse HuggingFace URL: {e}")
    
    def _parse_generic_url(self, url: str) -> Dict[str, Any]:
        """
        Parse generic URLs and extract basic information.
        """
        try:
            # Extract filename from URL path
            parsed_url = urllib.parse.urlparse(url)
            filename = os.path.basename(parsed_url.path)
            
            # If no filename in path, we'll determine it from server response
            if not filename or '.' not in filename:
                filename = None
            
            return {
                'download_url': url,
                'filename': filename,
                'source_type': 'generic',
                'original_url': url,
                'metadata': {}
            }
            
        except Exception as e:
            raise ValueError(f"Failed to parse generic URL: {e}")
    
    def get_filename_from_server(self, url: str) -> Optional[str]:
        """
        Get the actual filename from server response headers.
        
        Args:
            url: Download URL
            
        Returns:
            Filename from Content-Disposition header or URL path
        """
        try:
            print(f"Getting filename from server: {url}")
            
            # Make a HEAD request to get headers without downloading content
            response = self._request("HEAD", url, allow_redirects=True, timeout=30)
            
            print(f"Response status: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")
            
            # Check Content-Disposition header
            content_disposition = response.headers.get('Content-Disposition', '')
            if content_disposition:
                print(f"Content-Disposition: {content_disposition}")
                
                # Parse filename from Content-Disposition header
                # Handle both quoted and unquoted filenames
                filename_patterns = [
                    r'filename\*?=["\']?([^"\';\r\n]+)["\']?',
                    r'filename[^;=\n]*=(([\'"]).*?\2|[^;\n]*)',
                ]
                
                for pattern in filename_patterns:
                    filename_match = re.search(pattern, content_disposition, re.IGNORECASE)
                    if filename_match:
                        filename = filename_match.group(1).strip('\'"')
                        print(f"Extracted filename from Content-Disposition: {filename}")
                        return filename
            
            # For CivitAI, if HEAD doesn't work or returns HTML, try a GET request with Range header
            if 'civitai.com' in url.lower() and (response.status_code != 200 or 'text/html' in response.headers.get('Content-Type', '')):
                print("HEAD request failed for CivitAI or returned HTML, trying GET with Range header...")
                headers = {'Range': 'bytes=0-1023'}  # Request first 1KB only
                response = self._request("GET", url, headers=headers, timeout=30, allow_redirects=True)
                
                print(f"GET Range response status: {response.status_code}")
                print(f"GET Range response headers: {dict(response.headers)}")
                
                content_disposition = response.headers.get('Content-Disposition', '')
                if content_disposition:
                    print(f"Content-Disposition from GET: {content_disposition}")
                    
                    filename_patterns = [
                        r'filename\*?=["\']?([^"\';\r\n]+)["\']?',
                        r'filename[^;=\n]*=(([\'"]).*?\2|[^;\n]*)',
                    ]
                    
                    for pattern in filename_patterns:
                        filename_match = re.search(pattern, content_disposition, re.IGNORECASE)
                        if filename_match:
                            filename = filename_match.group(1).strip('\'"')
                            print(f"Extracted filename from GET Content-Disposition: {filename}")
                            return filename
            
            # Fallback to URL path
            parsed_url = urllib.parse.urlparse(response.url)
            filename = os.path.basename(parsed_url.path)
            
            if filename and '.' in filename:
                print(f"Using filename from URL path: {filename}")
                return filename
            
            print("No filename could be determined from server")
            return None
            
        except Exception as e:
            print(f"Warning: Could not get filename from server for {url}: {e}")
            return None
    
    def download_file(self, download_info: Dict[str, Any], target_dir: str, 
                     custom_filename: Optional[str] = None,
                     cancel_event=None) -> Tuple[bool, Optional[str]]:
        """
        Download a file using the robust downloader.
        
        Args:
            download_info: Dictionary from parse_url()
            target_dir: Target directory for download
            custom_filename: Optional custom filename override
            cancel_event: Optional cancellation event
            
        Returns:
            Tuple of (success: bool, final_filepath: Optional[str])
        """
        try:
            download_url = download_info['download_url']
            suggested_filename = download_info['filename']
            
            # Determine final filename
            final_filename = custom_filename
            if not final_filename:
                final_filename = suggested_filename
            
            # If we still don't have a filename, get it from server
            if not final_filename:
                final_filename = self.get_filename_from_server(download_url)
            
            # Last resort: generate a filename
            if not final_filename:
                timestamp = int(time.time())
                extension = self._guess_extension_from_url(download_url)
                final_filename = f"downloaded_file_{timestamp}{extension}"
            
            # Ensure target directory exists
            os.makedirs(target_dir, exist_ok=True)
            
            # Use the robust downloader for actual download
            # Pass token through so HuggingFace URLs can be authenticated (private repos / rate limits),
            # while still being safe if a token is invalid (RobustDownloader retries without it).
            downloader = RobustDownloader(self.config, hf_token=self.huggingface_api_key or False)
            if cancel_event:
                downloader.cancel_event = cancel_event
            
            final_path = os.path.join(target_dir, final_filename)
            
            # For non-HuggingFace URLs, we need to use a generic download method
            if download_info['source_type'] != 'huggingface':
                success = self._download_generic_file(downloader, download_url, final_path, cancel_event)
            else:
                # For HuggingFace, we could potentially use the HF-specific methods
                # but for simplicity, we'll use generic download for all
                success = self._download_generic_file(downloader, download_url, final_path, cancel_event)
            
            if success:
                return True, final_path
            else:
                return False, None
                
        except Exception as e:
            print(f"Error downloading file: {e}")
            return False, None
    
    def _download_generic_file(self, downloader: RobustDownloader, url: str, 
                              target_path: str, cancel_event=None) -> bool:
        """
        Download a file from a generic URL using the robust downloader's parallel download capabilities.
        """
        try:
            # Check for cancellation
            if cancel_event and cancel_event.is_set():
                return False
            
            print(f"Downloading from: {url}")
            print(f"Saving to: {target_path}")
            
            # Set cancel event on downloader
            if cancel_event:
                downloader.cancel_event = cancel_event
            
            # Get file size first to determine download method
            try:
                response = downloader._request("HEAD", url, timeout=30, allow_redirects=True)
                total_size = 0
                
                if response.status_code == 200:
                    # HEAD request successful - use Content-Length
                    total_size = int(response.headers.get('content-length', 0))
                    print(f"Got file size from HEAD request: {total_size}")
                else:
                    # HEAD failed (common with CivitAI) - try Range request
                    print(f"HEAD request failed (status {response.status_code}), trying Range request...")
                    headers = {'Range': 'bytes=0-1023'}
                    response = downloader._request("GET", url, headers=headers, timeout=30, allow_redirects=True)
                    
                    if response.status_code == 206:  # Partial Content
                        # Extract total size from Content-Range header
                        content_range = response.headers.get('content-range', '')
                        if content_range:
                            # Format: "bytes 0-1023/13875721488"
                            range_match = re.search(r'bytes \d+-\d+/(\d+)', content_range)
                            if range_match:
                                total_size = int(range_match.group(1))
                                print(f"Got file size from Content-Range: {total_size}")
                            else:
                                print(f"Could not parse Content-Range: {content_range}")
                        else:
                            print("No Content-Range header in 206 response")
                    else:
                        # Range not supported, try regular GET for size
                        print(f"Range request failed (status {response.status_code}), trying streaming GET...")
                        response = downloader._request("GET", url, stream=True, timeout=30)
                        total_size = int(response.headers.get('content-length', 0))
                        response.close()
                        print(f"Got file size from streaming GET: {total_size}")
                
            except Exception as e:
                print(f"Warning: Could not determine file size: {e}")
                total_size = 0
            
            filename = os.path.basename(target_path)
            
            # Use the robust downloader's methods based on file size
            if total_size > 0:
                print(f"File size: {downloader.format_bytes(total_size)}")
                
                # Use parallel download for files > 10MB, single connection for smaller files
                if total_size > 10 * 1024 * 1024:  # 10MB threshold
                    print(f"Using parallel download (16 connections) for large file")
                    success = downloader.download_parallel(url, target_path, filename, total_size)
                else:
                    print(f"Using single connection download for small file")
                    success = downloader.download_single(url, target_path, filename, total_size)
            else:
                # Unknown size - use the unknown size download method
                print(f"File size unknown, using streaming download")
                success = downloader.download_unknown_size(url, target_path, filename, "", "")
            
            if success:
                print(f"✅ Robust download completed: {target_path}")
                return True
            else:
                print(f"❌ Robust download failed: {target_path}")
                return False
                
        except Exception as e:
            print(f"Error in robust generic file download: {e}")
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except:
                    pass
            return False
    
    def _guess_extension_from_url(self, url: str) -> str:
        """
        Guess file extension from URL or content type.
        """
        # Common model file extensions
        common_extensions = ['.safetensors', '.ckpt', '.pt', '.pth', '.bin']
        
        url_lower = url.lower()
        for ext in common_extensions:
            if ext in url_lower:
                return ext
        
        # Default to .bin if we can't determine
        return '.bin'
    
    def validate_url(self, url: str) -> Tuple[bool, str]:
        """
        Validate if a URL is accessible and downloadable.
        
        Args:
            url: URL to validate
            
        Returns:
            Tuple of (is_valid: bool, message: str)
        """
        try:
            # Parse the URL first
            download_info = self.parse_url(url)
            download_url = download_info['download_url']
            
            # Make a HEAD request to check if URL is accessible
            response = self._request("HEAD", download_url, allow_redirects=True, timeout=30)
            
            if response.status_code == 200:
                content_length = response.headers.get('content-length')
                if content_length:
                    size_mb = int(content_length) / (1024 * 1024)
                    return True, f"✓ URL is valid. File size: {size_mb:.1f} MB"
                else:
                    return True, "✓ URL is valid. File size: Unknown"
            elif response.status_code == 405:  # Method Not Allowed (HEAD not supported)
                # Try a GET request with range header to check accessibility
                headers = {'Range': 'bytes=0-1023'}  # Request first 1KB
                response = self._request("GET", download_url, headers=headers, timeout=30)
                if response.status_code in [200, 206]:  # 206 = Partial Content
                    return True, "✓ URL is valid (HEAD not supported, but GET works)"
                else:
                    return False, f"✗ URL returned status code: {response.status_code}"
            else:
                return False, f"✗ URL returned status code: {response.status_code}"
                
        except requests.exceptions.Timeout:
            return False, "✗ URL validation timed out"
        except requests.exceptions.ConnectionError:
            return False, "✗ Could not connect to URL"
        except Exception as e:
            return False, f"✗ URL validation failed: {str(e)}"


def create_url_downloader(config: Optional[Dict] = None, civitai_api_key: Optional[str] = None, huggingface_api_key: Optional[str] = None) -> URLDownloader:
    """
    Factory function to create a URL downloader instance.
    
    Args:
        config: Optional download configuration
        civitai_api_key: Optional CivitAI API key for authenticated downloads
        huggingface_api_key: Optional HuggingFace API key for private repositories and higher rate limits
        
    Returns:
        URLDownloader instance
    """
    return URLDownloader(config, civitai_api_key, huggingface_api_key)


# Example usage and testing
if __name__ == "__main__":
    # Test URLs
    test_urls = [
        "https://civitai.com/models/1940709/retro-anime?modelVersionId=2196504",
        "https://civitai.com/models/302872/lizmix?modelVersionId=1451507",
        "https://huggingface.co/SG161222/RealVisXL_V5.0/resolve/main/RealVisXL_V5.0_fp16.safetensors?download=true"
    ]
    
    downloader = create_url_downloader()
    
    for url in test_urls:
        print(f"\nTesting URL: {url}")
        try:
            info = downloader.parse_url(url)
            print(f"Parsed info: {json.dumps(info, indent=2)}")
            
            is_valid, message = downloader.validate_url(url)
            print(f"Validation: {message}")
            
        except Exception as e:
            print(f"Error: {e}")
