"""Start the budget app:  python run.py   (then open http://localhost:8000)

    python run.py --lan     also reachable from your phone on the same Wi-Fi
    python run.py --port 8080
"""
import argparse
import os
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_PYTHON = HERE / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

# If started with the system Python, switch to the project's virtualenv.
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != (HERE / ".venv").resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])

import uvicorn  # noqa: E402


def lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the Wi-Fi interface
            return s.getsockname()[0]
    except OSError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the budget app")
    parser.add_argument("--lan", action="store_true",
                        help="listen on your local network so your phone can reach it")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    os.chdir(HERE)
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    print(f"\n  Budget app running at http://localhost:{args.port}", flush=True)
    if args.lan:
        ip = lan_ip()
        print(f"  Quick-add URL for your phone (same Wi-Fi): "
              f"http://{ip or '<your-mac-ip>'}:{args.port}/api/expenses/quick", flush=True)
        print("  (Other devices can only use quick-add; the full app stays on this computer.)", flush=True)
    print("  Press Ctrl+C to stop.\n", flush=True)
    uvicorn.run("app.main:app", host=host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
