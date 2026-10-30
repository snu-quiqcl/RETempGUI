"""Shared cooperative cancellation contract for operations."""


class OperationCancelled(Exception):
    """Stop execution; hardware remains at its last applied state."""


class ResourceBusy(RuntimeError):
    """A different operation owns the device."""


class UnexpectedReadback(RuntimeError):
    """The observed value differs from the expected value."""
