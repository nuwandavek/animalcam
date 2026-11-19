import argparse
import logging
import sys
import time
from importlib.metadata import version
from pathlib import Path

from .config import Settings
from .runner import Worker, run_once, safe_error


def main():
    parser = argparse.ArgumentParser(description="animalcam — a wildlife image journal")
    parser.add_argument("mode", nargs="?", choices=["run-once", "loop", "serve"], default="run-once")
    parser.add_argument("--cam")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--frame", type=Path)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        logging.info("yt-dlp %s", version("yt-dlp"))
        settings = Settings.load()
        settings.cams()
        if args.mode != "run-once" and (args.cam or args.dry_run or args.frame):
            parser.error("--cam, --frame and --dry-run apply to run-once mode")
        if args.mode == "serve":
            import uvicorn
            from .web import create_app
            uvicorn.run(create_app(settings), host=args.host, port=args.port, access_log=False)
        elif args.mode == "loop":
            worker = Worker(settings)
            worker.start()
            try:
                while True:
                    time.sleep(1)
            finally:
                worker.stop()
        else:
            results = run_once(settings, args.cam, dry_run=args.dry_run, frame=args.frame)
            return int(any(r["status"] == "error" for r in results))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logging.error("%s", safe_error(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
