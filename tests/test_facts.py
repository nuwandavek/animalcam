import copy
import json

import httpx
import pytest

from animalcam import analyze as vision, facts
from animalcam.store import Store, utcnow


def add_species(settings, observation, species):
    result = copy.deepcopy(observation)
    result["animals"][0].update(species=species, confidence=.9)
    store = Store(settings.state_dir)
    store.insert(settings.cams()[0], utcnow().isoformat(), "ok", result=result)
    return store, result


def test_bootstrap_fact_is_cached_and_unidentified_species_are_skipped(settings, observation, monkeypatch):
    store, result = add_species(settings, observation, "ostrich")
    add_species(settings, observation, "unidentified bird")
    def unexpected(*args): raise AssertionError("A known fact must not cause a paid lookup")
    monkeypatch.setattr(facts, "research_fact", unexpected)
    assert facts.enrich_facts(settings) == {"ready": 1}
    assert Store(settings.state_dir).fact(result)["source"] == "San Diego Zoo"
    assert facts.enrich_facts(settings) == {"ready": 1}


def test_new_species_is_researched_once_and_failures_are_deferred(settings, observation, monkeypatch):
    store, result = add_species(settings, observation, "black-backed jackal")
    lookups = []
    def research(species, cfg, db, cam):
        lookups.append(species)
        return {"title": "A fact", "text": "A sourced fact.", "source": "Zoo",
                "url": "https://animals.sandiegozoo.org/animals/jackal"}
    monkeypatch.setattr(facts, "research_fact", research)
    assert facts.enrich_facts(settings) == {"ready": 1}
    assert store.fact(result)["title"] == "A fact"
    facts.enrich_facts(settings)
    assert lookups == ["black-backed jackal"]
    add_species(settings, observation, "leopard")
    def fail(*args): lookups.append("failure"); raise ValueError("No reliable source")
    monkeypatch.setattr(facts, "research_fact", fail)
    facts.enrich_facts(settings); facts.enrich_facts(settings)
    assert lookups.count("failure") == 1
    with store.db() as db:
        row = db.execute("SELECT status,attempts,next_retry_at_utc FROM species_facts WHERE species='leopard'").fetchone()
    assert row["status"] == "error" and row["attempts"] == 1 and row["next_retry_at_utc"]


@pytest.mark.parametrize("url,visited,valid", [
    ("https://animals.sandiegozoo.org/animals/zebra", "https://animals.sandiegozoo.org/animals/zebra", True),
    ("https://evil.example/zebra", "https://evil.example/zebra", False),
    ("https://animals.sandiegozoo.org/animals/zebra", "https://animals.sandiegozoo.org/animals/lion", False),
])
def test_research_requires_trusted_retrieved_source_and_tracks_search_cost(settings, monkeypatch, url, visited, valid):
    def handle(request):
        payload = json.loads(request.content)
        assert payload["tools"][0]["type"] == "web_search"
        assert payload["max_tool_calls"] == 2
        fact = {"found": True, "title": "Individual stripes", "text": "Each zebra has its own stripe pattern.", "source": "San Diego Zoo", "url": url}
        return httpx.Response(200, json={"id": "fact-response", "model": "gpt-6-luna", "status": "completed",
            "usage": {"input_tokens": 1000, "output_tokens": 100}, "output": [
                {"type": "web_search_call", "action": {"sources": [{"url": visited}]}},
                {"type": "message", "content": [{"type": "output_text", "text": json.dumps(fact)}]}]})
    real_client = httpx.Client
    monkeypatch.setattr(vision.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handle)))
    store = Store(settings.state_dir)
    if valid:
        assert facts.research_fact("plains zebra", settings, store, "waterhole")["url"] == url
    else:
        with pytest.raises(ValueError): facts.research_fact("plains zebra", settings, store, "waterhole")
    with store.db() as db:
        call = db.execute("SELECT * FROM llm_calls").fetchone()
    assert call["source"] == "fact_research" and call["web_search_calls"] == 1
    assert call["estimated_cost_usd"] == pytest.approx(.01 + .0001 + .00005)
