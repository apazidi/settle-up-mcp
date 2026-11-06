"""Load local secrets and support a windowless Windows startup process."""
from pathlib import Path
import sys

from dotenv import load_dotenv


def run() -> None:
    root = Path(__file__).resolve().parent.parent
    # pythonw has no console streams. Keep diagnostics in ignored local files.
    if sys.stderr is None:
        logs = root / ".local"
        logs.mkdir(exist_ok=True)
        sys.stderr = (logs / "server-startup.log").open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = sys.stderr
    load_dotenv(root / ".env", override=True)
    from settleup_mcp.server import main
    main()


if __name__ == "__main__":
    run()
