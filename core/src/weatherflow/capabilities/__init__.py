"""Canonical capability contracts."""

from weatherflow.capabilities.catalog import (
    CapabilityCatalog,
    DuplicateToolError,
    UnknownToolError,
)
from weatherflow.capabilities.coordinator import (
    CapabilityFreezeResult,
    CapabilitySnapshotCoordinator,
)
from weatherflow.capabilities.models import (
    IdempotencyKind,
    ToolEffect,
    ToolHealth,
    ToolSpec,
)
from weatherflow.capabilities.repository import (
    CapabilitySnapshotRepository,
    DuplicateCapabilitySnapshot,
)
from weatherflow.capabilities.resolver import CapabilityResolver
from weatherflow.capabilities.snapshots import RunCapabilitySnapshot

__all__ = [
    "CapabilityCatalog",
    "CapabilityFreezeResult",
    "CapabilityResolver",
    "CapabilitySnapshotRepository",
    "CapabilitySnapshotCoordinator",
    "DuplicateToolError",
    "DuplicateCapabilitySnapshot",
    "IdempotencyKind",
    "RunCapabilitySnapshot",
    "ToolEffect",
    "ToolHealth",
    "ToolSpec",
    "UnknownToolError",
]
