from factory.flux_art import flux_lora_workflow


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
