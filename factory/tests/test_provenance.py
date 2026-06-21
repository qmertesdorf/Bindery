import json
from factory import provenance
from factory.config import BookConfig, Character
from factory.flux_art import BASE_UNET
from factory import specs


def _concept_cfg(**over):
    base = dict(slug="dbw", title="Deep Blue World", subtitle="s",
                author="Hannah Whitfield", illustrator="Grace Sullivan",
                art_prompt="ocean scene", book_type="concept", art_engine="flux",
                subject="ocean animals", flux_style="soft watercolour",
                flux_guidance=2.4, page_count=20, trim_w=8.5, trim_h=8.5)
    base.update(over)
    return BookConfig(**base)


def _content():
    return {"art_style": "soft watercolour", "dedication": "for the sea",
            "pages": [{"subject": "whale", "text": "t1", "scene": "a whale dives"},
                      {"subject": "crab", "text": "t2", "scene": "a crab walks"}],
            "closing": "bye"}


def test_build_provenance_records_recipe_seeds_and_rights():
    rec = provenance.build_provenance(_concept_cfg(), _content(), seed=100,
                                      flagged=[2])
    assert rec["slug"] == "dbw" and rec["illustrator"] == "Grace Sullivan"
    art = rec["art"]
    assert art["engine"] == "flux" and art["base_model"] == BASE_UNET
    assert art["upscale_px"] == specs.print_art_px(8.5, 8.5)
    assert art["upscale_model"].startswith("lanczos")        # none configured here
    # deterministic seed schedule: page i -> seed + i*17, cover -> seed + 42
    assert [p["seed"] for p in art["pages"]] == [117, 134]
    assert art["cover_seed"] == 142
    assert rec["pages_flagged_for_review"] == [2]
    # rights note keeps KDP disclosure and USCO registration distinct
    assert "kdp_ai_disclosure" in rec["rights"] and "usco_registration" in rec["rights"]


def test_build_provenance_records_configured_upscale_model():
    rec = provenance.build_provenance(
        _concept_cfg(upscale_model="RealESRGAN_x4plus.pth"), _content(), seed=1)
    assert rec["art"]["upscale_model"] == "RealESRGAN_x4plus.pth"


def test_build_provenance_lists_loras_for_character_books():
    cfg = _concept_cfg(
        book_type="picture", pet_kind="dog", pet_name="Biscuit",
        characters=(Character(role="hero", lora="boy.safetensors",
                              trigger="b1scuitboy boy", strength=0.9),))
    rec = provenance.build_provenance(cfg, _content(), seed=1)
    assert rec["art"]["loras"] == [
        {"lora": "boy.safetensors", "trigger": "b1scuitboy boy", "strength": 0.9}]


def test_write_provenance_emits_valid_json(tmp_path):
    out = provenance.write_provenance(_concept_cfg(), _content(), tmp_path, seed=5)
    assert out.name == "provenance.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["title"] == "Deep Blue World"
    assert data["art"]["qa_policy"]["candidates"] == 1
    assert data["art"]["qa_policy"]["tifa"] is False
    assert data["art"]["qa_policy"]["tifa_threshold"] == 0.4
