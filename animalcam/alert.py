import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx


def species_set(result):
    return {a["species"].strip().casefold() for a in result["animals"] if a["confidence"] >= .5}


def should_alert(result, last_alert, at, settings):
    current = species_set(result)
    if not result["interesting"] or result["interesting_score"] < settings.threshold or not current:
        return False
    if not last_alert or current != species_set(last_alert["result"]):
        return True
    return datetime.fromisoformat(at) - datetime.fromisoformat(last_alert["checked_at_utc"]) >= timedelta(minutes=settings.cooldown)


def send(cam, result, frame, at, settings):
    animals = ", ".join(f"{a['count']} {a['species']}" for a in result["animals"])
    local = datetime.fromisoformat(at).astimezone(ZoneInfo(cam.timezone)).strftime("%Y-%m-%d %H:%M %Z")
    title = f"{cam.name}: {animals}"
    message = f"{result['interesting_reason']} · {local} · {cam.url}"
    with httpx.Client(timeout=30) as client:
        if settings.backend == "ntfy":
            topic = os.getenv("NTFY_TOPIC")
            if not topic:
                raise ValueError("NTFY_TOPIC is required for ntfy alerts")
            # httpx only accepts ASCII headers. RFC 2047 encoding preserves UTF-8 text.
            from email.header import Header
            headers = {"Title": Header(title, "utf-8").encode(),
                       "Message": Header(message, "utf-8").encode(),
                       "Click": cam.url, "Filename": "sighting.jpg", "Content-Type": "image/jpeg"}
            if os.getenv("NTFY_TOKEN"):
                headers["Authorization"] = "Bearer " + os.environ["NTFY_TOKEN"]
            response = client.post(os.getenv("NTFY_URL", "https://ntfy.sh").rstrip("/") + "/" + topic,
                                   content=frame.read_bytes(), headers=headers)
        elif settings.backend == "discord":
            webhook = os.getenv("WEBHOOK_URL")
            if not webhook:
                raise ValueError("WEBHOOK_URL is required for Discord alerts")
            response = client.post(webhook, data={"payload_json": json.dumps({"content": (title + "\n" + message)[:2000]})},
                                   files={"files[0]": ("sighting.jpg", frame.read_bytes(), "image/jpeg")})
        else:
            return
        response.raise_for_status()
