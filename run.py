"""Run Budget from source:  python run.py   (opens the app in its own window)

    python run.py --lan        also let your phone reach the quick-add API (port 8000)
    python run.py --port 8080  use a fixed port instead of a free one
    python run.py --debug      enable the web inspector (right-click > Inspect)
    python run.py --browser    no window: just run the server at http://localhost:8000
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

os.chdir(HERE)


def lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the Wi-Fi interface
            return s.getsockname()[0]
    except OSError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Budget app from source")
    parser.add_argument("--lan", action="store_true",
                        help="listen on your local network so your phone can use quick-add")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--debug", action="store_true", help="enable the web inspector")
    parser.add_argument("--browser", action="store_true",
                        help="don't open a window; serve the app for a web browser instead")
    args = parser.parse_args()

    from app import config

    if args.lan:
        port = args.port or config.lan_port()
        print(f"\n  Quick-add URL for your phone (same Wi-Fi): "
              f"http://{lan_ip() or '<your-mac-ip>'}:{port}/api/expenses/quick", flush=True)
        print("  (Other devices can only use quick-add; the full app stays on this computer.)", flush=True)
    print(f"  Data: {config.DB_PATH}\n", flush=True)

    if args.browser:
        import uvicorn
        from app.db import init_db, migrate_legacy_data
        migrate_legacy_data()
        init_db()
        port = args.port or 8000
        print(f"  Open http://localhost:{port} — press Ctrl+C to stop.\n", flush=True)
        from app.email_sync import Poller
        Poller().start()
        uvicorn.run("app.main:app", host="0.0.0.0" if args.lan else "127.0.0.1", port=port, log_level="warning")
        return

    from app.desktop import main as desktop_main
    desktop_main(lan=args.lan or None, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
