"""
Spatial Relationship Graph — output of Layer 2 (Spatial Reasoning).

Consumes a RoomPerception (Layer 1 output) and produces:
  1. A STRUCTURAL graph layer: nodes (objects + zones) and typed edges
     (spatial relationships). This is the internal representation that
     algorithms operate on.
  2. An ANALYTICAL layer: computed issues, identified focal points, zones,
     and ranked observations. This is what gets fed to Layer 4 (the LLM).

DESIGN PRINCIPLE: anything deterministic-enough-to-compute lives here, so
the LLM in Layer 4 can spend its budget on judgment, not on rediscovering
geometry. If we can detect a problem algorithmically, we detect it here
and emit it as an Issue. If detection requires aesthetic judgment, we emit
a Fact and let Layer 4 interpret it.

WHAT THIS SCHEMA IS NOT:
- It is not the Design Specification (Layer 4 output)
- It does not propose changes — it only describes the current room
- It does not include style or aesthetic judgments
- It is not a 3D scene representation — Layer 5 builds that from Layer 4 output
"""

from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field

# Re-use primitives from Layer 1
from .room_perception import Vec2, Vec3, ObjectClass


# ============================================================================
# STRUCTURAL LAYER — the literal graph
# ============================================================================
#
# Nodes are typed: most are object nodes (1:1 with Layer 1 DetectedObjects),
# but we also introduce ZONE nodes (computed spatial regions) and FOCAL_POINT
# nodes (computed significance) so edges can reference them uniformly.


class NodeKind(str, Enum):
    OBJECT = "object"          # 1:1 with a DetectedObject in Layer 1
    ZONE = "zone"              # a computed spatial region (e.g. "seating zone")
    FOCAL_POINT = "focal_point"  # a computed point of visual significance


class ZoneKind(str, Enum):
    """Functional zones inferred from object clusters and free floor regions."""
    SEATING = "seating"           # cluster of seating + coffee table
    SLEEPING = "sleeping"         # bed + nightstands
    WORK = "work"                 # desk + office chair
    DINING = "dining"             # dining table + chairs
    STORAGE = "storage"           # bookshelf/dresser cluster
    CIRCULATION = "circulation"    # traffic path between doorways
    DEAD_ZONE = "dead_zone"       # unused floor region of significant size
    ENTRY = "entry"               # area immediately inside a doorway


class FocalPointKind(str, Enum):
    """Why this point is visually significant."""
    WINDOW_LIGHT = "window_light"        # primary natural light source
    FIREPLACE = "fireplace"
    TV_OR_SCREEN = "tv_or_screen"
    ARTWORK = "artwork"
    ARCHITECTURAL = "architectural"      # exposed beam, archway, niche
    INTENDED_FOCAL = "intended_focal"    # heuristic: the thing most seating points at


class Node(BaseModel):
    """Polymorphic node. Exactly one of object_ref / zone / focal_point is set."""
    id: str  # e.g. "node_obj_001", "node_zone_seating_0", "node_focal_0"
    kind: NodeKind
    
    # If kind == OBJECT
    object_ref: Optional[str] = None  # id of the Layer 1 DetectedObject
    
    # If kind == ZONE
    zone_kind: Optional[ZoneKind] = None
    zone_polygon: Optional[list[Vec2]] = None  # floor polygon
    zone_member_object_ids: list[str] = []  # objects belonging to this zone
    zone_area_normalized: Optional[float] = None
    
    # If kind == FOCAL_POINT
    focal_kind: Optional[FocalPointKind] = None
    focal_position: Optional[Vec3] = None
    focal_strength: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    focal_anchor_object_id: Optional[str] = None  # if anchored to an object


# ---------- Edges ----------
#
# Edges are typed. Each edge type has its own payload. We keep them in
# separate lists rather than as a single polymorphic list, because (a)
# the LLM consumes them by category, and (b) different edge types have
# very different fields and packing them into one schema gets ugly.


class FacingRelation(BaseModel):
    """A FROM B by what angle. Computed from B's facing_direction and A's position."""
    from_node_id: str  # the oriented object
    to_node_id: str    # what it faces (object, zone, or focal_point)
    angle_offset_radians: float  # 0 = directly facing, π = facing away
    is_primary: bool   # is this the dominant thing A is facing?


class AdjacencyRelation(BaseModel):
    """Two objects are spatially adjacent (within proximity threshold)."""
    a_node_id: str
    b_node_id: str
    separation_normalized: float  # gap between bbox edges
    is_against_same_wall: bool
    relationship_kind: Literal[
        "touching",
        "near",
        "across_from",
        "same_wall_neighbor",
    ]


class BlockingRelation(BaseModel):
    """A blocks B in some functional sense."""
    blocker_node_id: str
    blocked_node_id: str
    blocking_kind: Literal[
        "sight_line",        # blocks a view from a sight line source to a focal point
        "traffic_path",      # blocks the inferred circulation path
        "light_path",        # blocks light from a window from reaching an area
        "access",            # blocks access to a doorway, window, or outlet
    ]
    severity: float = Field(ge=0.0, le=1.0)


class ComplementaryRelation(BaseModel):
    """Two objects relate in a functionally complementary way."""
    a_node_id: str
    b_node_id: str
    complement_kind: Literal[
        "set",              # nightstand + bed, coffee_table + sofa
        "matched_pair",     # two armchairs flanking a fireplace
        "anchored_to",      # rug anchors a seating zone
    ]


class CompetingRelation(BaseModel):
    """Two objects compete for the same resource (light, attention, traffic space)."""
    a_node_id: str
    b_node_id: str
    competing_for: Literal[
        "natural_light",       # both need window light, only one can have the best spot
        "focal_attention",     # two competing focal points
        "traffic_space",       # both encroach on same circulation path
        "wall_space",          # both want the same wall
    ]
    severity: float = Field(ge=0.0, le=1.0)


class StructuralGraph(BaseModel):
    """The literal node-and-edge representation. Algorithms operate on this;
    the LLM rarely consumes it directly."""
    nodes: list[Node]
    facing_relations: list[FacingRelation]
    adjacency_relations: list[AdjacencyRelation]
    blocking_relations: list[BlockingRelation]
    complementary_relations: list[ComplementaryRelation]
    competing_relations: list[CompetingRelation]


# ============================================================================
# ANALYTICAL LAYER — interpreted conclusions, fed to Layer 4
# ============================================================================
#
# Two kinds of output:
#   - Issue: a detected problem (deterministic detection, prescriptive)
#   - Observation: a structured fact that's relevant but not a clear problem
#
# Issues are for things we're confident are wrong. Observations are for
# things the LLM should know but might or might not want to act on.


class IssueSeverity(str, Enum):
    BLOCKING = "blocking"      # the room doesn't really function
    SIGNIFICANT = "significant"  # clearly suboptimal
    MINOR = "minor"            # worth noting


class IssueKind(str, Enum):
    """Algorithmically detectable problems. Each kind has a specific
    detection rule documented in code."""
    
    # Traffic & access
    BLOCKED_TRAFFIC_PATH = "blocked_traffic_path"
    INSUFFICIENT_CLEARANCE = "insufficient_clearance"
    BLOCKED_DOORWAY = "blocked_doorway"
    BLOCKED_WINDOW_ACCESS = "blocked_window_access"
    
    # Sight & focal
    SEATING_FACES_BLANK_WALL = "seating_faces_blank_wall"
    NO_CLEAR_FOCAL_POINT = "no_clear_focal_point"
    COMPETING_FOCAL_POINTS = "competing_focal_points"
    BLOCKED_PRIMARY_SIGHT_LINE = "blocked_primary_sight_line"
    
    # Light
    SEATING_BACK_TO_PRIMARY_LIGHT = "seating_back_to_primary_light"
    DESK_FACES_LIGHT_GLARE_RISK = "desk_faces_light_glare_risk"
    NO_ARTIFICIAL_LIGHT_IN_DARK_ZONE = "no_artificial_light_in_dark_zone"
    
    # Proportion & scale
    OVERSIZED_FURNITURE = "oversized_furniture"
    UNDERSIZED_FURNITURE = "undersized_furniture"
    UNBALANCED_VISUAL_WEIGHT = "unbalanced_visual_weight"
    
    # Spatial waste
    LARGE_DEAD_ZONE = "large_dead_zone"
    UNDERUSED_WINDOW_WALL = "underused_window_wall"
    
    # Functional
    MISSING_FUNCTIONAL_ZONE = "missing_functional_zone"  # e.g. living room with no seating zone
    ZONE_CONFLICT = "zone_conflict"  # work zone overlaps sleeping zone in studio


class Issue(BaseModel):
    """An algorithmically detected problem in the room.
    
    Every Issue has a deterministic detection rule. If we can't write the
    rule in code, it should be an Observation instead.
    """
    id: str
    kind: IssueKind
    severity: IssueSeverity
    
    # What's involved
    involved_node_ids: list[str]
    
    # Quantitative backing — the measurement that triggered detection
    measurement: dict  # e.g. {"clearance_normalized": 0.18, "convention_min": 0.30}
    
    # Plain-language description (for prompting consistency, not for end-user display)
    description: str
    
    # Detection confidence — reflects upstream perception confidence
    confidence: float = Field(ge=0.0, le=1.0)


class ObservationKind(str, Enum):
    """Structured facts that don't rise to the level of issues but are
    relevant context for design reasoning."""
    
    # Light
    PRIMARY_LIGHT_DIRECTION = "primary_light_direction"
    LIGHT_QUALITY_SUMMARY = "light_quality_summary"
    
    # Sight lines
    PRIMARY_SIGHT_LINE = "primary_sight_line"
    WASTED_SIGHT_LINE = "wasted_sight_line"
    
    # Proportion
    ROOM_ASPECT_RATIO = "room_aspect_ratio"
    CEILING_HEIGHT_CHARACTER = "ceiling_height_character"  # low/standard/lofty
    
    # Density & balance
    VISUAL_DENSITY = "visual_density"  # how packed the room is
    LEFT_RIGHT_BALANCE = "left_right_balance"  # weight distribution
    
    # Materials
    MATERIAL_PALETTE_SUMMARY = "material_palette_summary"
    COLOR_TEMPERATURE_TILT = "color_temperature_tilt"
    
    # Anchors
    HEAVIEST_FIXED_ELEMENT = "heaviest_fixed_element"  # the thing we have to design around


class Observation(BaseModel):
    """A structured fact. Layer 4 interprets whether this is a problem."""
    id: str
    kind: ObservationKind
    involved_node_ids: list[str] = []
    payload: dict  # kind-specific structured data
    description: str


# ---------- Functional zones, focal points, and traffic ----------


class FunctionalZoneSummary(BaseModel):
    """Top-level summary of detected zones — duplicates info from zone nodes
    in StructuralGraph, but in a form Layer 4 can quickly read."""
    zone_node_id: str
    zone_kind: ZoneKind
    is_complete: bool  # does this zone have all expected members?
    missing_typical_members: list[ObjectClass] = []  # e.g. seating zone with no coffee table
    coherence: float = Field(ge=0.0, le=1.0)  # how cleanly clustered are the members


class FocalPointRanking(BaseModel):
    """Ranked focal points, strongest first."""
    focal_node_id: str
    focal_kind: FocalPointKind
    rank: int  # 1 = primary
    strength: float = Field(ge=0.0, le=1.0)
    is_oriented_toward: list[str]  # node ids of objects facing this focal point


class TrafficAnalysis(BaseModel):
    """Analysis of how people move through the room."""
    primary_path_polyline: list[Vec2]  # the inferred main circulation path
    primary_path_min_width_normalized: float
    primary_path_min_width_meets_convention: bool  # convention: ~90cm normalized equivalent
    secondary_paths: list[list[Vec2]] = []
    pinch_points: list[dict] = []  # [{position: Vec2, width_normalized: float}]


class LightAnalysis(BaseModel):
    """Computed light distribution across the room."""
    primary_light_direction: Vec3  # from the dominant source
    primary_source_node_id: str
    # Coarse floor-plane illumination map: divide floor into a grid, estimate
    # relative illumination per cell from light sources + occluders.
    illumination_grid_resolution: int  # e.g. 8 for an 8x8 grid
    illumination_grid: list[list[float]]  # [row][col], values in [0,1]
    dark_zone_polygons: list[list[Vec2]] = []  # floor regions below threshold


# ============================================================================
# TOP-LEVEL
# ============================================================================


class SpatialRelationshipGraph(BaseModel):
    """The complete output of Layer 2."""
    
    schema_version: str = "0.1.0"
    perception_image_id: str  # links to the RoomPerception this was built from
    
    # Structural layer — for algorithms
    structural: StructuralGraph
    
    # Analytical layer — for Layer 4 (the LLM)
    issues: list[Issue]
    observations: list[Observation]
    
    # Computed summaries — convenient packaging of analytical conclusions
    functional_zones: list[FunctionalZoneSummary]
    focal_point_ranking: list[FocalPointRanking]
    traffic_analysis: TrafficAnalysis
    light_analysis: LightAnalysis
    
    # Capability flags — Layer 4 should check these before relying on outputs
    perception_had_metric_scale: bool
    perception_had_orientation: bool
    perception_had_complete_floor_coverage: bool
    
    # If perception was weak in some area, some analyses degrade
    light_analysis_reliable: bool  # False if too few light sources detected
    traffic_analysis_reliable: bool  # False if doorways missing or unclear
    focal_ranking_reliable: bool  # False if too few oriented objects
    
    # Overall
    overall_graph_confidence: float = Field(ge=0.0, le=1.0)
