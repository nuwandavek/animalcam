import argparse
import json
import logging
import sys
import time
from importlib.metadata import version
from pathlib import Path

from .config import Settings
from .runner import Worker, run_once, safe_error


def main():
    parser = argparse.ArgumentParser(description="animalcam — a wildlife image journal")
    parser.add_argument("mode", nargs="?", choices=["run-once", "loop", "serve", "backfill-costs", "refresh-facts"], default="run-once")
    parser.add_argument("--samples", type=int, default=2, help="Calibration calls for backfill-costs (default 2)")
    parser.add_argument("--species", help="Refresh a cached species fact in refresh-facts mode")
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
        if args.species and args.mode != "refresh-facts":
            parser.error("--species applies to refresh-facts mode")
        if args.mode != "run-once" and (args.cam or args.dry_run or args.frame):
            parser.error("--cam, --frame and --dry-run apply to run-once mode")
        if args.mode == "refresh-facts":
            from .facts import enrich_facts
            print(json.dumps(enrich_facts(settings, refresh_species=args.species), indent=2))
        elif args.mode == "backfill-costs":
            from .backfill import backfill_costs
            print(json.dumps(backfill_costs(settings, args.samples), indent=2))
        elif args.mode == "serve":
            import uvicorn
            from .web import create_app
            uvicorn.run(create_app(settings), host=args.host, port=args.port, access_log=False)
        elif args.mode == "loop":
            from .facts import FactWorker
            facts = FactWorker(settings)
            worker = Worker(settings)
            facts.start()
            worker.start()
            try:
                while True:
                    time.sleep(1)
            finally:
                facts.stop()
                worker.stop()
        else:
            results = run_once(settings, args.cam, dry_run=args.dry_run, frame=args.frame)
            if not args.dry_run:
                from .facts import enrich_facts
                enrich_facts(settings)
            return int(any(r["status"] == "error" for r in results))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logging.error("%s", safe_error(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
