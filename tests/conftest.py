import json

import pytest

from animalcam.config import Settings


@pytest.fixture
def settings(tmp_path):
    cams = tmp_path / "cams.toml"
    cams.write_text('''[[cam]]
id = "waterhole"
name = "Waterhole"
url = "https://www.youtube.com/watch?v=test"
timezone = "Africa/Windhoek"
''')
    return Settings(tmp_path / "data", cams, "test-key", "gpt-6-luna", "https://api.openai.com/v1",
                    15, 6, 60, 0, "none", "", "animalcam", False, False)


@pytest.fixture
def observation():
    return {"animals": [{"species": "ostrich", "group": "bird", "count": 3,
                         "confidence": .95, "behaviors": ["drinking"], "notes": "At the water"}],
            "scene": "Three ostriches at the waterhole.", "interesting": True,
            "interesting_score": 8, "interesting_reason": "Ostriches newly arrived.",
            "events": ["New bird sighting"], "local_time_from_overlay": None}
