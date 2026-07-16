"""Re-export shim for the Scene model.

The canonical source is roomstudio_api_core.scene (packages/api-core). This
shim exists so api-internal modules can use the shorter
`from scene import ...` import path.

Do not add logic here. Edits to the Scene model go in
packages/api-core/roomstudio_api_core/scene.py.
"""
from roomstudio_api_core.scene import (  # noqa: F401
    InvalidTransitionError,
    Scene,
    SceneStatus,
    allowed_transitions,
    new_scene,
    validate_transition,
)
