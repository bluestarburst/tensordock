"""
HTTP proxy service for TensorDock server.
Handles sudo HTTP requests and Jupyter API proxying.
"""

import json
import datetime
from typing import Dict, Any, Optional
import requests

# Use absolute imports to avoid relative import issues
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import LoggerMixin, debug_log
from core.config import ServerConfig


class HTTPProxyService(LoggerMixin):
    """Handles HTTP proxy requests to Jupyter server."""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        self.base_url = config.jupyter_url  # Remove /lab to access API directly
        self.headers = config.get_jupyter_headers()
        
        # Request statistics
        self.request_stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'requests_by_method': {},
            'start_time': datetime.datetime.now()
        }
        
        debug_log(f"🌐 [HTTPProxy] HTTP proxy service initialized", {
            "base_url": self.base_url,
            "has_headers": bool(self.headers)
        })
    
    async def sudo_http_request(self, url: str, method: str, body: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Execute an HTTP request with elevated privileges."""
        try:
            # CRITICAL: Validate inputs to prevent errors
            if url is None:
                raise ValueError("URL cannot be None")
            
            if method is None:
                raise ValueError("Method cannot be None")
            
            # Ensure body is not None for logging
            safe_body = body if body is not None else {}
            
            # debug_log(f"🌐 [HTTPProxy] Processing sudo HTTP request", {
            #     "url": url,
            #     "method": method,
            #     "body_keys": list(safe_body.keys()) if isinstance(safe_body, dict) else [],
            #     "timestamp": datetime.datetime.now().isoformat()
            # })
            
            # Update statistics
            self.request_stats['total_requests'] += 1
            self.request_stats['requests_by_method'][method] = self.request_stats['requests_by_method'].get(method, 0) + 1
            
            # Build full URL - CRITICAL: Prevent double http:// issues
            if url.startswith('http://') or url.startswith('https://'):
                # URL is already absolute, use as-is
                full_url = url
                debug_log(f"🌐 [HTTPProxy] Using absolute URL as-is", {
                    "url": url,
                    "full_url": full_url
                })
            else:
                # URL is relative, construct full URL
                # Remove leading slash to avoid double slashes
                clean_url = url.lstrip('/') if url else ''
                full_url = f"{self.base_url}/{clean_url}" if clean_url else self.base_url
                debug_log(f"🌐 [HTTPProxy] Constructed relative URL", {
                    "url": url,
                    "clean_url": clean_url,
                    "base_url": self.base_url,
                    "full_url": full_url
                })
            
            # Execute request
            response = await self._execute_request(full_url, method, body, headers)
            
            if response['status'] < 400:
                self.request_stats['successful_requests'] += 1
                debug_log(f"✅ [HTTPProxy] Request successful", {
                    "url": url,
                    "method": method,
                    "status": response['status']
                })
            else:
                self.request_stats['failed_requests'] += 1
                debug_log(f"❌ [HTTPProxy] Request failed", {
                    "url": url,
                    "method": method,
                    "status": response['status']
                })
            
            return response
            
        except Exception as e:
            self.request_stats['failed_requests'] += 1
            
            debug_log(f"❌ [HTTPProxy] Request error", {
                "url": url,
                "method": method,
                "error": str(e),
                "error_type": type(e).__name__
            })
            
            return {
                'status': 500,
                'data': f"Error: {str(e)}",
                'headers': {},
                'error': str(e),
                'error_type': type(e).__name__
            }
    
    async def _execute_request(self, url: str, method: str, body: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Execute the actual HTTP request."""
        try:
            # Prepare request parameters
            # CRITICAL: Merge custom headers with default Jupyter headers
            request_headers = self.headers.copy()
            if headers:
                request_headers.update(headers)
                debug_log(f"🌐 [HTTPProxy] Merged headers", {
                    "default_headers": list(self.headers.keys()),
                    "custom_headers": list(headers.keys()),
                    "final_headers": list(request_headers.keys())
                })
            
            kwargs = {
                'headers': request_headers,
                'timeout': 30
            }
            
            # CRITICAL: Always ensure body is properly handled
            # Even if body is None or empty, we need to handle it properly
            if body is not None:
                # Handle both string and object bodies
                # Frontend sends stringified JSON from JupyterLab
                if isinstance(body, str):
                    try:
                        # Parse string to get the actual data
                        parsed_body = json.loads(body)
                        kwargs['json'] = parsed_body
                        debug_log(f"🌐 [HTTPProxy] Parsed string body to JSON", {
                            "original_body_type": type(body),
                            "parsed_body_keys": list(parsed_body.keys()) if isinstance(parsed_body, dict) else []
                        })
                    except json.JSONDecodeError:
                        # If it's not valid JSON, send as data
                        kwargs['data'] = body
                        debug_log(f"🌐 [HTTPProxy] Sending string body as data (not JSON)")
                else:
                    # Body is already an object, send as JSON
                    kwargs['json'] = body
                    debug_log(f"🌐 [HTTPProxy] Sending object body as JSON", {
                        "body_type": type(body),
                        "body_keys": list(body.keys()) if isinstance(body, dict) else []
                    })
            else:
                # CRITICAL: Ensure empty body is handled properly
                # Some Jupyter endpoints require an empty JSON body even for GET requests
                if method.upper() in ['POST', 'PUT', 'PATCH']:
                    kwargs['json'] = {}
                    debug_log(f"🌐 [HTTPProxy] Adding empty JSON body for {method} request")
            
            # Execute request based on method in a thread pool to avoid blocking
            import asyncio
            loop = asyncio.get_event_loop()
            
            def make_request():
                try:
                    if method.upper() == 'GET':
                        response = requests.get(url, **kwargs)
                    elif method.upper() == 'POST':
                        debug_log(f"🌐 [HTTPProxy] Making POST request", {
                            "url": url,
                            "kwargs": kwargs,
                            "body_type": type(body).__name__ if body else None
                        })
                        response = requests.post(url, **kwargs)
                    elif method.upper() == 'PUT':
                        response = requests.put(url, **kwargs)
                    elif method.upper() == 'DELETE':
                        response = requests.delete(url, **kwargs)
                    elif method.upper() == 'PATCH':
                        response = requests.patch(url, **kwargs)
                    else:
                        raise ValueError(f"Unsupported HTTP method: {method}")
                    
                    # Log response details for debugging
                    debug_log(f"🌐 [HTTPProxy] Response received", {
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "content_length": len(response.content) if response.content else 0
                    })
                    
                    return response
                except Exception as e:
                    debug_log(f"❌ [HTTPProxy] Request failed in make_request", {
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "url": url,
                        "method": method,
                        "kwargs": kwargs
                    })
                    raise
            
            # Run the synchronous request in a thread pool
            response = await loop.run_in_executor(None, make_request)
            
            # Parse response
            try:
                response_data = response.json() if response.content else {}
            except json.JSONDecodeError:
                response_data = response.text
            
            # Log detailed response information for debugging
            debug_log(f"🌐 [HTTPProxy] Response parsing completed", {
                "status_code": response.status_code,
                "content_type": response.headers.get('content-type'),
                "data_type": type(response_data).__name__,
                "data_preview": str(response_data)[:200] if response_data else None
            })
            
            return {
                'status': response.status_code,
                'data': response_data,
                'headers': dict(response.headers),
                'url': url,
                'method': method
            }
            
        except requests.exceptions.RequestException as e:
            debug_log(f"❌ [HTTPProxy] Request exception", {
                "url": url,
                "method": method,
                "error": str(e),
                "error_type": type(e).__name__
            })
            raise
    
    
    def get_status(self) -> Dict[str, Any]:
        """Get HTTP proxy service status."""
        uptime = datetime.datetime.now() - self.request_stats['start_time']
        total = self.request_stats['total_requests']
        success_rate = (self.request_stats['successful_requests'] / max(total, 1)) * 100
        
        return {
            'total_requests': total,
            'successful_requests': self.request_stats['successful_requests'],
            'failed_requests': self.request_stats['failed_requests'],
            'success_rate': success_rate,
            'requests_by_method': dict(self.request_stats['requests_by_method']),
            'uptime_seconds': uptime.total_seconds(),
            'base_url': self.base_url
        }
    
    async def cleanup(self):
        """Clean up HTTP proxy service resources."""
        debug_log(f"🧹 [HTTPProxy] Cleaning up HTTP proxy service")
        
        # Clear statistics
        self.request_stats.clear()
        
        debug_log(f"🧹 [HTTPProxy] HTTP proxy service cleanup completed")
