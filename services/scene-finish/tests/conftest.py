"""Put the service folder and the room-look package on the path, as the image does."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE, HERE.parent, HERE.parents[2] / "packages" / "room-look"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
