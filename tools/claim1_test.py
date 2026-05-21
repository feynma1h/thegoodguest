"""
Claim-1 Test Harness — minimal version.

Compares two LLM responses for the same room:
  Prompt A: image + question (vision-only baseline)
  Prompt B: hand-crafted SpatialRelationshipGraph JSON + question (no image)

Both use the same model and the same question. The model and question are
constants so the only variable is "image vs structured graph as input."

Output: a single markdown file with both responses side by side, ready for
human scoring.

Usage:
    export ANTHROPIC_API_KEY=...
    python claim1_test.py --room room1 --image path/to/photo.jpg --graph test_data/graph_room1.json

Each (image, graph) pair is one test row. Run multiple times for multiple rooms
and the harness appends to results.md.
"""

import argparse
import base64
import json
import sys
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic


MODEL = "claude-opus-4-7"  # use the same model for both prompts — only the input differs
MAX_TOKENS = 1500

QUESTION = """Suggest three specific changes to improve this room. For each change, explain why.

Be specific: name the objects involved, describe what moves where, and ground your reasoning in the room's actual geometry, light, and relationships — not generic design advice."""


def _extract_text(response) -> str:
    """Concatenate text content blocks. Future-proof against multi-block responses."""
    return "\n".join(block.text for block in response.content if block.type == "text")


def call_with_image(client: Anthropic, image_path: Path) -> str:
    """Prompt A: image + question."""
    image_bytes = image_path.read_bytes()
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    
    # Infer media type from extension
    suffix = image_path.suffix.lower()
    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(suffix)
    if media_type is None:
        raise ValueError(f"Unsupported image extension: {suffix}")
    
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": QUESTION},
            ],
        }],
    )
    return _extract_text(response)


def call_with_graph(client: Anthropic, graph_path: Path) -> str:
    """Prompt B: graph JSON + question. No image."""
    graph_json = graph_path.read_text()
    
    prompt = f"""You are reasoning about a room. You will not see a photo — instead, you receive a SpatialRelationshipGraph: a structured analysis of the room produced by a perception and reasoning pipeline.

The graph includes:
- `structural.nodes`: every object, zone, and focal point in the room
- `structural.facing_relations`, `adjacency_relations`, `blocking_relations`, `complementary_relations`, `competing_relations`: typed edges
- `issues`: algorithmically detected problems with measurements
- `observations`: structured facts about the room
- `functional_zones`, `focal_point_ranking`, `traffic_analysis`, `light_analysis`: computed summaries

Coordinates are in room-normalized units (longest dimension = 1.0). Convert to meters using `geometry.dimensions.scale_factor_m` if you need physical measurements.

Here is the graph:

```json
{graph_json}
```

{QUESTION}"""
    
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_text(response)


def write_results(room_id: str, response_a: str, response_b: str, output_path: Path) -> None:
    """Append both responses to a markdown file for side-by-side scoring."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    
    section = f"""
---

# Room: `{room_id}`  ·  {timestamp}

## Prompt A — image only

{response_a}

## Prompt B — graph JSON only

{response_b}

## Scoring (fill in by hand)

| Criterion | A wins / B wins / Tie | Notes |
|---|---|---|
| Specificity (names objects, gives measurements) | | |
| Falsifiability (could this have been written about any room?) | | |
| Spatial reasoning (cites clearances, sight lines, light, traffic) | | |

**Verdict for this room:** _____

"""
    with output_path.open("a") as f:
        f.write(section)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--room", required=True, help="Room identifier, e.g. 'room1'")
    parser.add_argument("--image", required=True, type=Path, help="Path to room photo")
    parser.add_argument("--graph", required=True, type=Path, help="Path to graph JSON")
    parser.add_argument("--output", type=Path, default=Path("results.md"))
    args = parser.parse_args()
    
    if not args.image.exists():
        print(f"Image not found: {args.image}", file=sys.stderr)
        return 1
    if not args.graph.exists():
        print(f"Graph not found: {args.graph}", file=sys.stderr)
        return 1
    
    client = Anthropic()
    
    print(f"[{args.room}] Calling Prompt A (image)...")
    response_a = call_with_image(client, args.image)
    
    print(f"[{args.room}] Calling Prompt B (graph)...")
    response_b = call_with_graph(client, args.graph)
    
    write_results(args.room, response_a, response_b, args.output)
    print(f"[{args.room}] Done. Appended to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
