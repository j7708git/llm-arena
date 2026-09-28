"""讓 `python -m arena` 也能執行 CLI。"""

import sys

from arena.cli import main

if __name__ == "__main__":
    sys.exit(main())
