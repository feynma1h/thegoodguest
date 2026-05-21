"""roomstudio schemas: Pydantic models for the perception/reasoning pipeline.

Layer 1 (RoomPerception): geometric facts extracted by the perception pipeline.
Layer 2 (SpatialRelationshipGraph): interpretations and analytical conclusions.
"""
from .room_perception import RoomPerception  # noqa: F401
from .spatial_graph import SpatialRelationshipGraph  # noqa: F401
