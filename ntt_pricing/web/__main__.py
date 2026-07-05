"""Launch the local web app: ``python -m ntt_pricing.web``."""
from __future__ import annotations

import argparse
import threading
import webbrowser

from .app import create_app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="ntt-pricing-web",
        description="Run the NTT Pricing Tool web interface locally.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true",
                        help="Do not auto-open a browser window.")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    app = create_app()
    url = f"http://{args.host if args.host != '0.0.0.0' else '127.0.0.1'}:{args.port}"
    print(f"NTT Pricing Tool — open {url}  (Ctrl+C to stop)")

    if not args.no_browser and not args.debug:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
