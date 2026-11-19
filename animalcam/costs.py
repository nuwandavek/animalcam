"""USD estimates from reported token usage; these are not billing invoices."""
import os
import math

# Standard GPT-6 Luna rates, verified 2026-11-19:
# https://developers.openai.com/api/docs/models/gpt-6-luna
LUNA_RATES = {"input": .10, "cached_input": .01, "cache_write": .125, "output": .50}


def pricing(model):
    defaults = LUNA_RATES if model == "gpt-6-luna" or model.startswith("gpt-6-luna-") else None
    names = {"input": "ANIMALCAM_INPUT_USD_PER_MILLION",
             "cached_input": "ANIMALCAM_CACHED_INPUT_USD_PER_MILLION",
             "cache_write": "ANIMALCAM_CACHE_WRITE_USD_PER_MILLION",
             "output": "ANIMALCAM_OUTPUT_USD_PER_MILLION"}
    if defaults is None and not all(os.getenv(name) for name in names.values()):
        return None
    rates = {kind: float(os.getenv(name, str((defaults or {})[kind])))
             for kind, name in names.items()} if defaults else {kind: float(os.environ[name]) for kind, name in names.items()}
    if any(not math.isfinite(rate) or rate < 0 for rate in rates.values()):
        raise ValueError("Token prices must be finite and nonnegative")
    return rates


def usage_details(usage, model):
    rates = pricing(model)
    usage = usage or {}
    incoming, outgoing = usage.get("input_tokens"), usage.get("output_tokens")
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
    written = (usage.get("input_tokens_details") or {}).get("cache_write_tokens", 0)
    reasoning = (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0)
    cost = None
    if rates and incoming is not None and outgoing is not None:
        cached = min(cached, incoming)
        written = min(written, incoming - cached)
        # Reasoning is already included in output_tokens; do not charge it twice.
        cost = ((incoming - cached - written) * rates["input"] + cached * rates["cached_input"]
                + written * rates["cache_write"]
                + outgoing * rates["output"]) / 1_000_000
    return {"input_tokens": incoming, "cached_input_tokens": cached,
            "cache_write_tokens": written,
            "output_tokens": outgoing, "reasoning_tokens": reasoning,
            "estimated_cost_usd": cost, "rates": rates}
