"""
Room Perception JSON — output of Layer 1 (Perception).

REVISION 0.2.0
Changes from 0.1.0:
  - Scale strategy is "ratio-first" (Strategy C from pressure-test): all spatial
    reasoning downstream uses ratios; absolute meters are present but marked
    optional/low-confidence unless a user reference is provided (Strategy A).
  - Orientation: per-class semantic flag; high-stakes classes get a second-pass
    VLM verification (refined_by_vlm=True).
  - color_temperature_kelvin replaced with categorical light quality estimate.
  - occluded_regions_fraction replaced with per-object is_partially_occluded.
  - Added openness model: doorways, free floor polygons, sight lines.
  - Multi-photo handled by treating the canonical view as primary and other
    views as supplementary_views (no geometric fusion in v0.1).
"""

from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ---------- Primitives ----------

class Vec2(BaseModel):
    """A 2D point — either image pixels or floor-plane coordinates depending on context."""
    x: float
    y: float


class Vec3(BaseModel):
    """A 3D vector in room-local coordinates.

    Origin: floor-plane centroid of the room.
    Units: normalized to room diagonal = 1.0 (NOT meters).
    Convert to meters using RoomGeometry.dimensions.scale_factor_m if and only if
    RoomGeometry.has_metric_scale is True.
    Axes: +X right, +Y up, +Z toward camera.
    """
    x: float
    y: float
    z: float


class BBox2D(BaseModel):
    """Axis-aligned bounding box in image pixel coordinates."""
    x_min: int
    y_min: int
    x_max: int
    y_max: int


class BBox3D(BaseModel):
    """Oriented bounding box in room-normalized coordinates (NOT meters).

    `yaw_radians` is meaningful only if the object's ObjectClass has
    semantic_orientation=True (see OBJECT_CLASS_HAS_ORIENTATION below).
    For classes without meaningful orientation, yaw_radians is 0.0 and
    yaw_confidence is 0.0 — do not interpret these fields.
    """
    center: Vec3
    size: Vec3  # width, height, depth in room-normalized units
    yaw_radians: float = 0.0
    yaw_confidence: float = Field(ge=0.0, le=1.0)
    yaw_refined_by_vlm: bool = False


class Provenance(BaseModel):
    """Where a field's value came from. Always attached to high-stakes fields."""
    source: Literal[
        "sam2_segmentation",
        "depth_anything_v2",
        "classification_head",
        "geometric_heuristic",
        "vlm_verification",
        "user_provided",
        "fused"
    ]
    confidence: float = Field(ge=0.0, le=1.0)


# ---------- Materials & Surfaces ----------

class MaterialClass(str, Enum):
    """Coarse material categories. Intentionally not fine-grained."""
    WOOD_LIGHT = "wood_light"
    WOOD_DARK = "wood_dark"
    FABRIC_SOFT = "fabric_soft"
    FABRIC_STRUCTURED = "fabric_structured"
    METAL = "metal"
    GLASS = "glass"
    LEATHER = "leather"
    STONE = "stone"
    PAINTED_SURFACE = "painted_surface"
    PLASTIC = "plastic"
    UNKNOWN = "unknown"


class ColorSample(BaseModel):
    """Dominant color extracted from a segmentation region, in LAB color space."""
    lab_l: float
    lab_a: float
    lab_b: float
    coverage: float = Field(ge=0.0, le=1.0)


class SurfaceMaterial(BaseModel):
    material: MaterialClass
    material_confidence: float = Field(ge=0.0, le=1.0)
    dominant_colors: list[ColorSample] = Field(max_length=3)


# ---------- Objects ----------

class ObjectClass(str, Enum):
    SOFA = "sofa"
    ARMCHAIR = "armchair"
    DINING_CHAIR = "dining_chair"
    OFFICE_CHAIR = "office_chair"
    BENCH = "bench"
    COFFEE_TABLE = "coffee_table"
    DINING_TABLE = "dining_table"
    DESK = "desk"
    SIDE_TABLE = "side_table"
    BOOKSHELF = "bookshelf"
    DRESSER = "dresser"
    CABINET = "cabinet"
    TV_STAND = "tv_stand"
    BED = "bed"
    NIGHTSTAND = "nightstand"
    RUG = "rug"
    CURTAIN = "curtain"
    CUSHION = "cushion"
    FLOOR_LAMP = "floor_lamp"
    TABLE_LAMP = "table_lamp"
    PENDANT_LIGHT = "pendant_light"
    PLANT = "plant"
    ARTWORK = "artwork"
    MIRROR = "mirror"
    WINDOW = "window"
    DOOR = "door"
    DOORWAY = "doorway"  # open passage, no door visible
    RADIATOR = "radiator"
    FIREPLACE = "fireplace"
    OUTLET = "outlet"
    UNKNOWN_FURNITURE = "unknown_furniture"


# Per-class semantic config. Drives the two-pass pipeline.
# Classes with semantic_orientation=True get VLM yaw verification.
OBJECT_CLASS_HAS_ORIENTATION: dict[ObjectClass, bool] = {
    ObjectClass.SOFA: True,
    ObjectClass.ARMCHAIR: True,
    ObjectClass.DINING_CHAIR: True,
    ObjectClass.OFFICE_CHAIR: True,
    ObjectClass.BENCH: True,
    ObjectClass.DESK: True,
    ObjectClass.BED: True,
    ObjectClass.TV_STAND: True,
    ObjectClass.BOOKSHELF: True,
    ObjectClass.DRESSER: True,
    ObjectClass.ARTWORK: True,
    ObjectClass.MIRROR: True,
    ObjectClass.FIREPLACE: True,
    ObjectClass.WINDOW: True,
    ObjectClass.DOOR: True,
    # Everything else defaults to False (no meaningful "front").
}


# Sight lines originate from these classes only. Other oriented objects (windows,
# fireplaces, doors) are TARGETS of sight lines, not SOURCES.
SIGHT_LINE_SOURCE_CLASSES: set[ObjectClass] = {
    ObjectClass.SOFA,
    ObjectClass.ARMCHAIR,
    ObjectClass.DINING_CHAIR,
    ObjectClass.OFFICE_CHAIR,
    ObjectClass.BENCH,
    ObjectClass.BED,
    ObjectClass.DESK,
}


class RoomPurposeCategory(str, Enum):
    """Categorical room purpose. Inferable from the image via VLM with ~95% accuracy.
    
    NOT to be confused with FUNCTIONAL purpose (how the user actually uses the space)
    or ASPIRATIONS (how they want it to feel) — those live in Layer 3 (Constraints)
    and are user-provided, not inferred.
    """
    LIVING_ROOM = "living_room"
    BEDROOM = "bedroom"
    KITCHEN = "kitchen"
    DINING_ROOM = "dining_room"
    HOME_OFFICE = "home_office"
    STUDIO = "studio"  # combined living/sleeping
    BATHROOM = "bathroom"
    HALLWAY = "hallway"
    NURSERY = "nursery"
    UNKNOWN = "unknown"


class MovabilityClass(str, Enum):
    MOVABLE = "movable"
    HEAVY_MOVABLE = "heavy_movable"
    FIXED = "fixed"
    SOFT_FURNISHING = "soft_furnishing"


class DetectedObject(BaseModel):
    id: str  # e.g. "obj_001"
    object_class: ObjectClass
    classification_confidence: float = Field(ge=0.0, le=1.0)
    class_refined_by_vlm: bool = False

    bbox_2d: BBox2D
    bbox_3d: BBox3D

    # Position descriptors (room-normalized)
    distance_to_nearest_wall_normalized: float = Field(ge=0.0, le=1.0)
    distance_to_nearest_wall_provenance: Provenance
    height_above_floor_normalized: float  # 0 = on floor, 1 = at ceiling

    # Occlusion — replaces the global occluded_regions_fraction
    is_partially_occluded: bool
    occlusion_reason: Optional[Literal[
        "image_boundary",
        "occluded_by_other_object",
        "occluded_by_wall"
    ]] = None

    movability: MovabilityClass
    surface_material: SurfaceMaterial

    # Orientation — only meaningful if OBJECT_CLASS_HAS_ORIENTATION[object_class] is True
    facing_direction: Optional[Vec3] = None
    facing_confidence: float = Field(ge=0.0, le=1.0, default=0.0)


# ---------- Light ----------

class LightQuality(str, Enum):
    """Categorical light quality. Replaces the dishonest Kelvin field.
    
    All values are best-effort categorical estimates with explicit confidence.
    """
    GOLDEN_WARM = "golden_warm"        # late afternoon, incandescent, tungsten
    NEUTRAL_DAYLIGHT = "neutral_daylight"  # midday natural
    COOL_DAYLIGHT = "cool_daylight"    # overcast, north light
    FLUORESCENT_COOL = "fluorescent_cool"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class LightSourceKind(str, Enum):
    WINDOW = "window"
    LAMP_FIXTURE = "lamp_fixture"
    OVERHEAD = "overhead"
    INFERRED_DIRECTIONAL = "inferred_directional"


class LightSource(BaseModel):
    id: str
    kind: LightSourceKind
    direction_estimate: Vec3
    direction_confidence: float = Field(ge=0.0, le=1.0)
    intensity_relative: float = Field(ge=0.0, le=1.0)  # relative within this room only
    quality: LightQuality
    quality_confidence: float = Field(ge=0.0, le=1.0)
    is_natural: bool


# ---------- Room geometry & openness ----------

class Doorway(BaseModel):
    """A doorway or door — passage to another space.
    
    Critical for spatial reasoning: defines required traffic clearance and
    constrains what can be placed where.
    """
    id: str
    object_ref: Optional[str] = None  # links to a DetectedObject id if visible
    floor_position: Vec2  # in room-normalized floor coordinates
    width_normalized: float
    wall_index: int  # which wall it's on (index into RoomGeometry.wall_planes)
    leads_to_visible_space: bool  # True if we can see into the next room
    provenance: Provenance


class FreeFloorPolygon(BaseModel):
    """A polygon on the floor plane that is free of obstacles.
    
    Computed by subtracting object floor-footprints from the room's floor polygon.
    The reasoning layer uses these to decide where new furniture can go.
    """
    vertices: list[Vec2]  # in room-normalized floor coordinates, CCW order
    area_normalized: float  # fraction of total floor area
    is_near_window: bool
    is_near_doorway: bool
    is_traffic_path: bool  # part of the inferred path between doorways


class RawSightLine(BaseModel):
    """A geometric sight line from an oriented object's facing direction.
    
    LAYER BOUNDARY NOTE: This is a Layer 1 GEOMETRIC FACT, not a Layer 2
    interpretation. We cast a ray from every oriented seating-class object
    along its facing direction and record what it hits. We do NOT label these
    as 'good' or 'bad' or 'wasted' — that's Layer 2's job (SightLineRelation
    edges in the SpatialRelationshipGraph).
    
    Emitted for every object where OBJECT_CLASS_HAS_ORIENTATION is True AND
    object_class is in SIGHT_LINE_SOURCE_CLASSES (seating + bed).
    """
    from_object_id: str
    # The ray endpoint, in normalized floor coordinates
    ray_endpoint: Vec2
    # What the ray hits first
    hits_object_id: Optional[str] = None  # None if it hits a wall first
    hits_wall_index: Optional[int] = None
    distance_to_hit_normalized: float
    # Geometric blocking: anything taller than seated-eye-level in the path
    intermediate_object_ids: list[str] = []  # things in the path, regardless of height
    is_geometrically_blocked: bool  # True if anything in path exceeds seated-eye-level


class RoomDimensions(BaseModel):
    """Room envelope.
    
    Primary representation is room-normalized (width/length/height as ratios
    where the longest dimension = 1.0). Metric scale is OPTIONAL.
    """
    # Always present — relative ratios
    width_normalized: float
    length_normalized: float
    height_normalized: float
    longest_dimension_axis: Literal["width", "length", "height"]
    
    # Optional — only filled if user provided a reference measurement (Strategy A)
    # or a very confident prior was available
    has_metric_scale: bool = False
    scale_factor_m: Optional[float] = None  # multiply normalized values by this for meters
    scale_factor_provenance: Optional[Provenance] = None


class RoomGeometry(BaseModel):
    dimensions: RoomDimensions
    floor_plane_normal: Vec3
    primary_view_direction: Vec3

    wall_planes: list[Vec3]  # wall normals
    wall_count_estimate: int  # may differ from len(wall_planes) due to occlusion
    ceiling_detected: bool
    ceiling_height_confidence: float = Field(ge=0.0, le=1.0)

    # Openness model
    doorways: list[Doorway]
    free_floor_polygons: list[FreeFloorPolygon]
    raw_sight_lines: list[RawSightLine]  # geometric only — Layer 2 will interpret

    # Cardinal orientation — user-provided or null
    north_direction: Optional[Vec3] = None
    orientation_source: Literal["user", "inferred_sun_shadow", "unknown"] = "unknown"
    orientation_confidence: float = Field(ge=0.0, le=1.0, default=0.0)


# ---------- Multi-view ----------

class SupplementaryView(BaseModel):
    """A non-canonical photo of the same room.
    
    For v0.1: NOT geometrically fused with the primary view. Available to the
    reasoning layer as visual context (passed to VLM during Layer 4 if helpful)
    but not parsed into the structured graph.
    """
    image_id: str
    image_width_px: int
    image_height_px: int
    # Lightweight extraction only — object classes present, no 3D
    object_classes_present: list[ObjectClass]


# ---------- Top-level ----------

class RoomPerception(BaseModel):
    """The complete output of Layer 1."""

    schema_version: str = "0.2.0"
    
    # Primary view — the canonical perception
    primary_image_id: str
    primary_image_width_px: int
    primary_image_height_px: int

    geometry: RoomGeometry
    objects: list[DetectedObject]
    light_sources: list[LightSource]
    overall_light_quality: LightQuality

    # Other photos of the same room, lightly processed
    supplementary_views: list[SupplementaryView] = []

    # Global confidence
    overall_perception_confidence: float = Field(ge=0.0, le=1.0)

    # Capability flags — downstream layers MUST check these before reasoning
    has_metric_scale: bool
    has_orientation: bool
    has_complete_floor_coverage: bool  # False if large floor regions are occluded
    
    # Inferred from image via VLM. Categorical only — functional purpose and
    # aspirations are user-provided in Layer 3.
    inferred_purpose: RoomPurposeCategory = RoomPurposeCategory.UNKNOWN
    inferred_purpose_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    
    # User-provided context (optional, collected during Act 3 conversation)
    user_provided_room_purpose: Optional[str] = None  # free text, may contradict inferred
    user_provided_reference_dimension: Optional[dict] = None  # e.g. {"object": "sofa", "width_m": 2.1}
