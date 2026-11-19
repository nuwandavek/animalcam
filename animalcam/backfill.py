"""Estimate old successful checks from a small number of explicitly requested calls."""
import json
from dataclasses import replace
from statistics import mean

from .analyze import analyze
from .config import Cam
from .costs import usage_details
from .store import Store


def backfill_costs(settings, samples=2):
    if not 1 <= samples <= 5:
        raise ValueError("Use 1–5 calibration samples")
    store = Store(settings.state_dir)
    with store.db() as db:
        pending = [dict(row) for row in db.execute("""SELECT * FROM checks c
            WHERE result_json IS NOT NULL AND (model=? OR model IS NULL)
            AND NOT EXISTS (SELECT 1 FROM llm_calls l WHERE l.check_id=c.id)
            ORDER BY id""", (settings.model,))]
    if not pending:
        return {"backfilled": 0, "sample_calls": 0, "costs": store.cost_summary()}
    available = []
    for row in pending:
        path = (settings.state_dir / (row["frame_path"] or "")).resolve()
        if path.is_relative_to((settings.state_dir / "frames").resolve()) and path.is_file():
            available.append(row)
    if not available:
        raise ValueError("Backfill needs at least one retained image for calibration")
    available.sort(key=lambda row: sum(a["count"] for a in json.loads(row["result_json"])["animals"]))
    # Historical calls used 1280px images. Sample a busy and a quiet scene at that
    # original width; future captures use the smaller configured width.
    examples = [available[-1], available[0]]
    calls, sample_ids = [], []
    for index in range(samples):
        row = examples[index % len(examples)]
        cam = Cam(row["cam_id"], row["cam_name"], row["url"], row["timezone"])
        with store.db() as db:
            previous = db.execute("SELECT result_json FROM checks WHERE cam_id=? AND id<? "
                "AND result_json IS NOT NULL ORDER BY id DESC LIMIT 1", (cam.id, row["id"])).fetchone()
        def record(call):
            call["source"] = "sample"
            sample_ids.append(store.record_call(cam.id, call))
            calls.append(call)
        analyze(settings.state_dir / row["frame_path"], cam,
                json.loads(previous[0]) if previous else None,
                replace(settings, image_width=1280), record_call=record)
    if not calls or any(call["estimated_cost_usd"] is None for call in calls):
        raise ValueError("Calibration returned no priced token usage; historical costs were not guessed")
    usage = {
        "input_tokens": round(mean(call["input_tokens"] for call in calls)),
        "output_tokens": round(mean(call["output_tokens"] for call in calls)),
        "input_tokens_details": {"cached_tokens": round(mean(call["cached_input_tokens"] for call in calls)),
                                 "cache_write_tokens": round(mean(call["cache_write_tokens"] for call in calls))},
        "output_tokens_details": {"reasoning_tokens": round(mean(call["reasoning_tokens"] for call in calls))},
    }
    estimate = usage_details(usage, settings.model)
    for row in pending:
        call = {**estimate, "created_at_utc": row["checked_at_utc"], "model": row["model"] or settings.model,
                "status": "ok", "image_width": 1280, "source": "backfill",
                "usage": {"approximate": True, "sample_call_ids": sample_ids, "average_usage": usage}}
        store.record_call(row["cam_id"], call, row["id"])
    return {"backfilled": len(pending), "sample_calls": len(calls),
            "estimated_usd_per_old_check": estimate["estimated_cost_usd"], "costs": store.cost_summary()}
