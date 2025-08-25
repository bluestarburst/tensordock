"""
Custom exception classes for TensorDock server.
"""


class TensorDockError(Exception):
    """Base exception for TensorDock server."""
    
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.details = details or {}
    
    def __str__(self):
        if self.details:
            return f"{super().__str__()} - {self.details}"
        return super().__str__()


class ConnectionError(TensorDockError):
    """Raised when there's a connection-related error."""
    pass


class KernelError(TensorDockError):
    """Raised when there's a kernel-related error."""
    pass


class WebRTCError(TensorDockError):
    """Raised when there's a WebRTC-related error."""
    pass


class JupyterError(TensorDockError):
    """Raised when there's a Jupyter-related error."""
    pass


class MessageError(TensorDockError):
    """Raised when there's a message processing error."""
    pass
