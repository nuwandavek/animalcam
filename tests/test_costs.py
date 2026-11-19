import json

import httpx
import pytest

from animalcam import analyze as vision, backfill, runner
from animalcam.costs import usage_details
from animalcam.store import Store, utcnow


USAGE = {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 200},
         "output_tokens": 400, "output_tokens_details": {"reasoning_tokens": 250}}


def test_cost_counts_cached_reads_writes_and_does_not_double_bill_reasoning():
    data = usage_details(USAGE, "gpt-6-luna")
    assert data["estimated_cost_usd"] == pytest.approx((700*.10 + 100*.01 + 200*.125 + 400*.50)/1_000_000)
    assert data["reasoning_tokens"] == 250
    assert usage_details(None, "gpt-6-luna")["estimated_cost_usd"] is None
    assert usage_details(USAGE, "unknown-model")["estimated_cost_usd"] is None


def test_failed_but_billed_response_is_saved_and_linked_to_error_check(settings, monkeypatch):
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
        "id": "response-test", "model": "gpt-6-luna", "status": "incomplete", "usage": USAGE}))
    monkeypatch.setattr(vision.httpx, "Client", lambda **kw: real_client(transport=transport))
    monkeypatch.setattr(vision, "image_data", lambda *args: "data:image/jpeg;base64,test")
    def grab(cam, path):
        path.parent.mkdir(parents=True); path.write_bytes(b"jpeg")
    monkeypatch.setattr(runner, "grab", grab)
    result = runner.run_once(settings)[0]
    assert result["status"] == "error"
    store = Store(settings.state_dir)
    call = store.get(result["id"])["llm_calls"][0]
    assert call["status"] == "error" and call["response_id"] == "response-test"
    assert call["input_tokens"] == 1000 and call["cache_write_tokens"] == 200
    assert call["estimated_cost_usd"] > 0
    assert store.cost_summary()["calls"] == 1


def test_backfill_uses_two_real_usage_samples_and_is_idempotent(settings, observation, monkeypatch):
    store = Store(settings.state_dir)
    cam = settings.cams()[0]
    ids = []
    for name, animals in [("quiet", []), ("busy", observation["animals"])]:
        frame = settings.state_dir / f"frames/{cam.id}/{name}.jpg"
        frame.parent.mkdir(parents=True, exist_ok=True); frame.write_bytes(b"jpeg")
        ids.append(store.insert(cam, utcnow().isoformat(), "ok", str(frame.relative_to(settings.state_dir)),
                                {**observation, "animals": animals}, model=settings.model))
    widths = []
    def sample(path, cam, previous, cfg, record_call):
        widths.append(cfg.image_width)
        record_call({**usage_details(USAGE, cfg.model), "usage": USAGE, "model": cfg.model,
                     "created_at_utc": utcnow().isoformat(), "status": "ok", "image_width": cfg.image_width})
        return observation
    monkeypatch.setattr(backfill, "analyze", sample)
    result = backfill.backfill_costs(settings)
    assert widths == [1280, 1280]
    assert result["sample_calls"] == 2 and result["backfilled"] == 2
    assert result["costs"]["calls"] == 4 and result["costs"]["backfilled_calls"] == 2
    for check_id in ids:
        call = store.get(check_id)["llm_calls"][0]
        assert call["source"] == "backfill"
        assert json.loads(call["usage_json"])["approximate"] is True
    again = backfill.backfill_costs(settings)
    assert again["sample_calls"] == 0 and again["backfilled"] == 0
    assert again["costs"] == result["costs"]
