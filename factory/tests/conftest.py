import json
from pathlib import Path
import pytest


@pytest.fixture
def sample_config_dict():
    return {
        "slug": "dog-loss",
        "title": "Paw Prints on My Heart",
        "subtitle": "A Guided Grief Journal for Coping with the Loss of a Beloved Dog",
        "author": "Your Name",
        "pet_kind": "dog",
        "prompt_count": 70,
        "art_prompt": "soft pastel watercolor of a dog at a rainbow bridge, gentle, tender, no text",
        "price_usd": 9.99,
    }


@pytest.fixture
def sample_config_file(tmp_path, sample_config_dict):
    p = tmp_path / "dog-loss.config.json"
    p.write_text(json.dumps(sample_config_dict), encoding="utf-8")
    return p


@pytest.fixture
def sample_content():
    return {
        "intro": "This journal is a gentle space to remember your companion.",
        "how_to_use": "Use these pages at your own pace. There is no right way to grieve.",
        "pet_profile_fields": ["Name", "Breed", "Birthday", "The day we met", "Favorite things"],
        "prompts": [f"Today I miss you because... (prompt {i})" for i in range(1, 71)],
        "milestones": ["The first week without you", "One month on", "Your birthday"],
        "section_microcopy": {"prompts": "Take your time with these.", "milestones": "Marking the hard days."},
        "letter_pages": ["A letter to you", "What I never got to say"],
    }
