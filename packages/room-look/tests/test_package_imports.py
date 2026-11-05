"""The modules moved out of tools/ import each other relatively, including the
imports made inside functions, which importing the package does not exercise."""
import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "thegoodguest_room_look"


def test_no_module_imports_a_sibling_by_its_bare_name():
    siblings = {p.stem for p in PKG.glob("*.py")} - {"__init__"}
    bad = []
    for p in PKG.glob("*.py"):
        for node in ast.walk(ast.parse(p.read_text())):
            names = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            bad += [f"{p.name}:{node.lineno} imports {n}" for n in names if n in siblings]
    assert not bad, bad
