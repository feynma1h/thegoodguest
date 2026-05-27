"""Re-export shim: Scene model has moved to packages/api-core.

The canonical source is roomstudio_api_core.scene. This shim preserves
`from scene import ...` in api-internal modules without requiring changes
to existing imports throughout this service.

Do not add logic here. Edits to the Scene model go in
packages/api-core/roomstudio_api_core/scene.py.
"""
from roomstudio_api_core.scene import (  # noqa: F401
    DeviceIdSource,
    InvalidTransitionError,
    Scene,
    SceneStatus,
    allowed_transitions,
    new_scene,
    validate_transition,
)
