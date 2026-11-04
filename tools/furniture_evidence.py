"""Command-line entry for the room look's `furniture_evidence` step. The code is in
packages/room-look (thegoodguest_room_look.furniture_evidence); `--help` shows its usage."""

import sys
from pathlib import Path

_repo = Path(__file__).resolve().parent.parent
for _p in (_repo / "packages/schemas", _repo / "packages/room-look"):
    sys.path.insert(0, str(_p))

from thegoodguest_room_look.furniture_evidence import main  # noqa: E402

if __name__ == "__main__":
    main()
