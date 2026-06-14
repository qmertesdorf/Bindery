from factory.flux_art import flux_lora_workflow
from factory.config import Character
from factory.flux_art import page_plan

HERO = Character(role="hero", lora="boy.safetensors", trigger="b1scuitboy boy",
                 strength=0.9)
DOG = Character(role="companion", lora="dog.safetensors", trigger="b1scuitdog dog",
                strength=0.85, appears_on="memory")


def test_page_plan_memory_uses_both_loras_and_dog_trigger():
    page = {"scene": "a sunny field", "moment": "memory", "mood": "happy"}
    prompt, loras = page_plan(page, hero=HERO, companion=DOG,
                              style="watercolour", outfit="a red sweater")
    assert loras == [("boy.safetensors", 0.9), ("dog.safetensors", 0.85)]
    assert "b1scuitboy boy" in prompt and "b1scuitdog dog" in prompt
    assert "a red sweater" in prompt
    assert "warm gentle smile" in prompt          # happy mood -> smiling


def test_page_plan_present_uses_hero_only_and_excludes_animals():
    page = {"scene": "an empty hallway", "moment": "present", "mood": "sad"}
    prompt, loras = page_plan(page, hero=HERO, companion=DOG,
                              style="watercolour", outfit="a red sweater")
    assert loras == [("boy.safetensors", 0.9)]
    assert "b1scuitdog dog" not in prompt
    assert "no animals" in prompt
    assert "not smiling" in prompt                # sad mood (in GRIEF) -> no smile


def test_page_plan_no_companion_treats_memory_as_hero_only():
    page = {"scene": "a field", "moment": "memory", "mood": "happy"}
    prompt, loras = page_plan(page, hero=HERO, companion=None,
                              style="w", outfit="o")
    assert loras == [("boy.safetensors", 0.9)]


def test_flux_workflow_puts_seed_on_noise_not_sampler():
    wf = flux_lora_workflow("a boy", 777, loras=[("boy.safetensors", 0.9)],
                            guidance=2.4)
    # Flux seeds the RandomNoise node, NOT a KSampler
    assert wf["noise"]["class_type"] == "RandomNoise"
    assert wf["noise"]["inputs"]["noise_seed"] == 777
    assert "KSampler" not in [n["class_type"] for n in wf.values()]
    assert wf["pos"]["inputs"]["text"] == "a boy"
    assert wf["fg"]["inputs"]["guidance"] == 2.4

def test_flux_workflow_single_lora_chain():
    wf = flux_lora_workflow("x", 1, loras=[("boy.safetensors", 0.9)], guidance=2.4)
    loras = {k: v for k, v in wf.items() if v["class_type"] == "LoraLoaderModelOnly"}
    assert len(loras) == 1
    assert wf["lora0"]["inputs"]["model"] == ["u", 0]       # first lora on the UNET
    assert wf["lora0"]["inputs"]["lora_name"] == "boy.safetensors"
    assert wf["lora0"]["inputs"]["strength_model"] == 0.9
    # the sampler chain reads from the LAST lora in the stack
    assert wf["sch"]["inputs"]["model"] == ["lora0", 0]
    assert wf["gd"]["inputs"]["model"] == ["lora0", 0]

def test_flux_workflow_stacks_two_loras_in_series():
    wf = flux_lora_workflow("x", 1, guidance=2.4,
                            loras=[("boy.safetensors", 0.9), ("dog.safetensors", 0.85)])
    assert wf["lora0"]["inputs"]["model"] == ["u", 0]          # boy on UNET
    assert wf["lora1"]["inputs"]["model"] == ["lora0", 0]      # dog on boy output
    assert wf["lora1"]["inputs"]["lora_name"] == "dog.safetensors"
    assert wf["lora1"]["inputs"]["strength_model"] == 0.85
    assert wf["sch"]["inputs"]["model"] == ["lora1", 0]        # chain head = last lora
    assert wf["gd"]["inputs"]["model"] == ["lora1", 0]
