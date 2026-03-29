class AgentRuntimeError(Exception):
    """Base class for Agent Runtime V2 errors."""


class AgentConfigurationError(AgentRuntimeError):
    """Raised when agent runtime config is invalid."""


class RoleNotAllowedForSurfaceError(AgentRuntimeError):
    """Raised when a role cannot be used on the requested surface."""


class AgentToolExecutionError(AgentRuntimeError):
    """Raised when a tool invocation fails."""


class AgentContinuationError(AgentRuntimeError):
    """Raised when continuing an existing run is invalid."""
