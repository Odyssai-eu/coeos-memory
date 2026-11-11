"""Coeos Memory: one long-term memory shared by every Claude mode."""

__version__ = "0.4.0"

# Set in the environment of every Claude process this package starts, so that
# its own hooks do not capture the sessions it creates.
INTERNAL_ENV = "COEOS_MEMORY_INTERNAL"
