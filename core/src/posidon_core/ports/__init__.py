"""Integration contracts required by the core pipeline."""

from .acquisition import SourceAcquirer
from .acquisition import SourceAcquisition
from .acquisition import SourceAcquisitionError
from .tagging import TagWriter
from .tagging import TagWriterFactory

__all__ = [
    "SourceAcquirer",
    "SourceAcquisition",
    "SourceAcquisitionError",
    "TagWriter",
    "TagWriterFactory",
]
"""Names supported as the ports package's public interface."""
