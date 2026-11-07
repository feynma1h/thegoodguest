"""The engine names no furniture type.

What a room needs comes from its needs file, which Claude writes per room
(needs.py). The code that decides what is allowed knows solids, the shell and
people, and no category. If a furniture word appears in that code as a name or
a string, a rule specific to some rooms has crept in, and this test fails.

Docstrings and comments may use furniture as examples, and so may sentences
meant for people (a string with a space in it, like the rulebook's words). A
rule keyed on furniture would need a bare token, like "bed", and those are
what this test looks for. Prompt text lives in modules listed in TEXT_MODULES
and is data, not rules.
"""
import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "thegoodguest_room_guide"

# Modules whose job is words for Claude or for the person, not rules.
TEXT_MODULES = {"prompts.py"}

FURNITURE = {
    "bed", "sofa", "couch", "chair", "armchair", "stool", "bench", "ottoman", "desk", "table",
    "dresser", "wardrobe", "closet", "bookcase", "bookshelf", "shelf", "cabinet", "cupboard",
    "nightstand", "mirror", "tv", "television", "monitor", "lamp", "rug", "carpet", "curtain",
    "blind", "radiator", "heater", "fireplace", "stove", "fridge", "refrigerator", "oven", "sink",
    "toilet", "bathtub", "shower", "crib", "cot", "piano", "plant", "ac", "fan", "speaker",
    "laptop", "console", "clutter", "art", "picture", "painting", "socket", "outlet", "switch",
}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z]+", text.lower()) if w}


def test_engine_code_names_no_furniture():
    offenders = []
    for path in sorted(PACKAGE.glob("*.py")):
        if path.name in TEXT_MODULES:
            continue
        tree = ast.parse(path.read_text())
        docs = _docstring_nodes(tree)
        for node in ast.walk(tree):
            text = None
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
                    and not re.search(r"\s", node.value)):
                text = node.value
            elif isinstance(node, ast.Name):
                text = node.id
            elif isinstance(node, ast.Attribute):
                text = node.attr
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.arg)):
                text = getattr(node, "name", None) or getattr(node, "arg", None)
            if text and (_words(text.replace("_", " ")) & FURNITURE):
                offenders.append(f"{path.name}:{getattr(node, 'lineno', '?')}: {text!r}")
    assert offenders == [], "furniture named in engine code:\n" + "\n".join(offenders)
