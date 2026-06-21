"""WS2 repair-before-reroll: mask geometry, the Flux-Fill inpaint graph, and the
InpaintRepairer orchestration — all exercised with fakes (no GPU/ComfyUI)."""
from pathlib import Path
from PIL import Image

from factory.repair import (mask_rects_from_defects, build_mask_image,
                            flux_fill_workflow, InpaintRepairer)
from factory.qa import Defect


# ---- mask geometry ----

def test_mask_rects_pad_and_clamp():
    rects = mask_rects_from_defects([Defect("hand", (50, 50, 70, 70), 0.9)],
                                    100, 100, pad_frac=0.1)
    # padded by 10px each side, clamped to the frame
    assert rects == [(40, 40, 80, 80)]

def test_mask_rects_clamp_to_frame_edges():
    rects = mask_rects_from_defects([Defect("limb", (5, 5, 95, 95), 0.9)],
                                    100, 100, pad_frac=0.2)
    assert rects == [(0, 0, 100, 100)]   # padding can't push past the frame

def test_mask_rects_accepts_raw_bbox_tuples():
    assert mask_rects_from_defects([(10, 10, 20, 20)], 100, 100, pad_frac=0) \
        == [(10, 10, 20, 20)]

def test_mask_rects_drops_degenerate_boxes():
    assert mask_rects_from_defects([Defect("x", (10, 10, 10, 10), 0.9)],
                                   100, 100, pad_frac=0) == []


# ---- mask image ----

def test_build_mask_image_white_inside_black_outside():
    m = build_mask_image([(20, 20, 40, 40)], 60, 60, blur=0)
    assert m.size == (60, 60) and m.mode == "L"
    assert m.getpixel((30, 30)) == 255   # inside the rect -> inpaint
    assert m.getpixel((5, 5)) == 0       # outside -> keep


# ---- Flux Fill graph ----

def test_flux_fill_workflow_wires_image_mask_prompt_seed():
    wf = flux_fill_workflow("src.png", "mask.png", "a fixed hand", 77,
                            guidance=30.0, steps=20)
    assert wf["img"]["inputs"]["image"] == "src.png"
    assert wf["msk"]["inputs"]["image"] == "mask.png"
    assert wf["pos"]["inputs"]["text"] == "a fixed hand"
    assert wf["noise"]["inputs"]["noise_seed"] == 77
    # Flux Fill model + localized-inpaint nodes are present
    assert wf["u"]["inputs"]["unet_name"] == "flux1-fill-dev.safetensors"
    assert wf["dd"]["class_type"] == "DifferentialDiffusion"
    assert wf["inp"]["class_type"] == "InpaintModelConditioning"
    assert wf["inp"]["inputs"]["noise_mask"] is True
    assert wf["save"]["class_type"] == "SaveImage"


# ---- InpaintRepairer orchestration ----

class _FakeComfy:
    def __init__(self): self.submitted = None
    def submit(self, workflow, *, out_path):
        self.submitted = workflow
        Path(out_path).write_bytes(b"REPAIRED")
        return Path(out_path)

def test_repairer_uploads_masks_and_overwrites_image(tmp_path):
    img = tmp_path / "page.png"
    img.write_bytes(b"orig")
    uploaded = []
    comfy = _FakeComfy()
    rep = InpaintRepairer(comfy, upload_fn=lambda p: uploaded.append(Path(p).name)
                          or Path(p).name, image_size_fn=lambda p: (100, 100))
    out = rep.repair(img, [Defect("hand", (10, 10, 30, 30), 0.9)],
                     prompt="fix the hand", seed=3)
    assert Path(out).read_bytes() == b"REPAIRED"          # image overwritten
    assert "page.png" in uploaded and "page__mask.png" in uploaded  # both uploaded
    assert comfy.submitted["pos"]["inputs"]["text"] == "fix the hand"
    assert not list(tmp_path.glob("*__mask.png"))         # mask cleaned up

def test_repairer_noop_when_boxes_clamp_to_nothing(tmp_path):
    img = tmp_path / "page.png"
    img.write_bytes(b"orig")
    comfy = _FakeComfy()
    rep = InpaintRepairer(comfy, upload_fn=lambda p: "x",
                          image_size_fn=lambda p: (100, 100))
    # a box wholly off the frame clamps away to nothing -> no mask, no submit
    out = rep.repair(img, [Defect("x", (200, 200, 210, 210), 0.9)], prompt="p")
    assert Path(out).read_bytes() == b"orig"   # untouched
    assert comfy.submitted is None             # never submitted

def test_repairer_is_drop_in_repair_fn_for_run_audited_render(tmp_path):
    # repair(image, defects, *, prompt, seed=0) matches the repair_fn contract
    from factory.art import run_audited_render
    img_seen = {}
    comfy = _FakeComfy()
    rep = InpaintRepairer(comfy, upload_fn=lambda p: "n",
                          image_size_fn=lambda p: (100, 100))
    class _Aud:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            if Path(image_path).read_bytes() == b"REPAIRED":
                return {"ok": True, "issues": []}
            return {"ok": False, "issues": ["bad hand"],
                    "defects": [Defect("hand", (10, 10, 30, 30), 0.9)]}
    def render(prompt, seed, out_path):
        img_seen["seed"] = seed; Path(out_path).write_bytes(b"orig")
    out = run_audited_render(render, "p", out_path=tmp_path / "p.png",
                             auditor=_Aud(), anchor="a", scene="s", seed=0,
                             max_tries=3, repair_fn=rep.repair)
    assert Path(out).read_bytes() == b"REPAIRED"
