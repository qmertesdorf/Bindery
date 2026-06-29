"""Vision auditor: judge an illustration for character consistency & cleanliness.

Injected exactly like generate_fn / ComfyClient so the art loop is testable with
a fake. The real adapter shells to the `claude` CLI, which can Read local image
files in print mode and return a JSON verdict.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Callable
from .content import _strip_fences, run_claude_cli, ContentError


class AuditError(RuntimeError):
    pass


# --- Shared judge-hardening clauses ----------------------------------------
# These encode documented LLM/VLM-as-judge defences so every prompt variant
# gets them (see docs/research): describe-then-judge to beat the text-prior
# bias, a strictness nudge to beat leniency bias, evidence-grounding so each
# call is checkable, and the Groh physics-tell category.

# Pixels-first: a VLM judge over-trusts the text spec and "sees" what the words
# say rather than the pixels — the single most-documented failure mode — and a
# polite "focus on the image" barely helps. So force a literal look BEFORE the
# spec below is weighed, and tell it the pixels win ties.
_PIXELS_FIRST = (
    "FIRST look at the picture ITSELF and note what you ACTUALLY see — the "
    "subject and its parts, plus anything in the corners and background. Do NOT "
    "assume the description or caption below is true of the image: judge only "
    "from the pixels, and let what you actually see OVERRIDE what the words say "
    "should be there.\n\n")

# Leniency bias: judges over-accept and wave borderline defects through. Bias the
# DEFECT LIST ONLY toward "prove it's clean" while staying generous elsewhere.
_STRICT_RULE = (
    " For the defect list below ONLY, default to REJECT when a listed defect is "
    "plausibly present — do NOT wave a borderline case through as 'probably "
    "fine', which is exactly how defects ship. (Stay generous on incidental "
    "style, pose, crop, lighting, and background variation.)")

# Evidence-grounding: require each issue to localize itself — steadies the judge
# and makes the reroll/repair targeted.
_EVIDENCE_RULE = (
    " For EACH issue you list, name WHERE you see it (which corner, edge, or body "
    "part) so it can be checked.")

# Physics tells (Groh et al. AI-artifact taxonomy): inconsistent light/shadow,
# impossible reflections, or broken perspective are common machine-render tells.
_PHYSICS_REJECT = (
    "\n- INCONSISTENT PHYSICS: light and shadow that disagree (shadows falling in "
    "different directions, or a shadow with no light source), impossible "
    "reflections, or broken perspective / scale — tells that the picture was "
    "machine-assembled rather than painted as one coherent scene;")


def build_audit_prompt(*, anchor: str, scene: str | None,
                       image_path: Path, reference_path: Path | None) -> str:
    ref = (f"\nA reference image of the recurring character(s) is at {reference_path}. "
           f"Read it: the character in the new image must be RECOGNISABLY THE SAME "
           f"character (same kind of person/animal, same defining features and outfit "
           f"colours) — it need NOT match the reference pose, angle, or background."
           if reference_path else "")
    scene_line = f"\nThis page is meant to depict, roughly: {scene}." if scene else ""
    return f"""Read the image file at {image_path} and judge it for a children's
picture book.{ref}

{_PIXELS_FIRST}The recurring character(s) should look like: {anchor}.{scene_line}

This is a soft, stylised storybook, so judge GENEROUSLY on incidental variation.
Apply a two-tier bar.{_STRICT_RULE}

REJECT (set ok=false) ONLY for a real defect that would break the book:
- the character is the WRONG character, or characters are CONFLATED (e.g. a
  different person/animal, an animal wearing the child's clothes, or an extra
  subject/animal that should not be present);
- the CHILD has any animal features bleeding onto its face or body — a dog or
  animal nose/snout/muzzle, fur, whiskers, paws, a tail, or animal ears in place
  of human ones. The child must be fully, recognisably human;
- any text, letters, words, or numbers are rendered in the artwork;
- broken anatomy (malformed faces, extra or missing limbs/eyes);
- the character's DEFINING outfit is clearly wrong — wrong colours, OR a clearly
  different GARMENT than the one described above for this character, OR a
  described key piece is missing or replaced. The described outfit (whatever it
  is) must be recognisably present;
- the child's expression clearly CONTRADICTS the mood the scene calls for — in
  particular a smiling, grinning, or visibly happy child on a sad, lonely,
  wistful, or grieving page (the face must read at least quiet/subdued there).

ACCEPT (set ok=true) — do NOT reject — for natural variation that keeps the
character recognisable:
- different hairstyle detail, pose, camera angle, or framing;
- a quiet/neutral expression on a somber page (it need not be tearful — gentle is
  fine), or a warm one on a happy page;
- a different or simpler background, lighting, or time of day;
- missing or rearranged minor scene props; the scene only needs to be roughly right.

When the character is recognisable and the art is clean, set ok=true even if such
details differ. Reserve issues for genuine defects.{_EVIDENCE_RULE}

Return ONLY JSON: {{"ok": true|false, "issues": ["short reason", ...]}}
Output the JSON and nothing else."""


def build_concept_audit_prompt(*, anchor: str, scene: str | None,
                               image_path: Path,
                               reference_path: Path | None = None,
                               caption: str | None = None) -> str:
    scene_line = f"\nThis page is meant to depict, roughly: {scene}." if scene else ""
    # General, book-agnostic anatomy guard: the per-page scene + caption already carry
    # the ground-truth anatomy (the author writes them species-correct, e.g. "a single
    # paddle tail, not forked", "exactly five arms — not six"), so rather than hardcode
    # a per-species checklist that every new book would outgrow, force the judge to
    # extract and LITERALLY verify the concrete claims already written above. Catches
    # the dolphin-tailed shark / bilobed-tail manatee that slipped through
    # ([[catch-defects-with-guards]]). Only meaningful when there is text to check.
    focused = (
        "\n\nFOCUSED FIDELITY CHECK — the scene description and caption above are the "
        "GROUND TRUTH for this page; the author wrote them to be anatomically correct. "
        "Before you decide, re-read them and pull out every CONCRETE, depictable claim "
        "about the subject's body — an exact COUNT of parts (arms, legs, eyes, fins, "
        "points, tentacles), a specific TAIL / FIN / BODY shape (e.g. 'a single paddle "
        "tail, not forked', 'a vertical tail with the top lobe taller', 'one flat "
        "diamond disc'), or a stated pose or action — then verify EACH one is LITERALLY "
        "true in the image. COUNT parts one by one around the whole outline rather than "
        "eyeballing the overall shape. Pay SPECIAL attention to any 'NOT ...' / 'not a "
        "...' warning in the scene (e.g. 'NOT a forked tail', 'not six arms') — the "
        "author added each one because that exact mistake is COMMON; if the image shows "
        "the very thing the scene says it must NOT be, that is an automatic reject. If "
        "any concrete claim in the scene or caption is contradicted or missing, set "
        "ok=false and name it, even when the rest of the picture is lovely."
        if (scene or caption) else "")
    caption_line = (
        f"\n\nCAPTION FIDELITY — a child will read this caption ALOUD beside the "
        f"picture:\n  \"{caption}\"\nThe picture must AGREE with it. If the caption "
        f"states a CONCRETE, depictable fact about the subject — a specific COUNT of "
        f"body parts (e.g. \"eight arms\", \"five arms\"), a clear ACTION or POSE the "
        f"subject is doing (e.g. \"wrapping its tail round the grass\", \"floats on "
        f"her back\", \"puffs up like a ball\", \"peeks out\", \"huddle together\"), "
        f"or a specific object it directly holds or touches — the image MUST actually "
        f"show that fact. Ignore figurative or non-visual phrases (\"as proud as can "
        f"be\", \"out of sight\", \"never to roam\", \"the largest of all\") and "
        f"ignore incidental background scenery." if caption else "")
    caption_reject = (
        "\n- CAPTION MISMATCH: the picture clearly CONTRADICTS or OMITS a concrete, "
        "depictable fact stated in the caption above — a stated COUNT of body parts, "
        "or the specific action, pose, or object the caption describes (see CAPTION "
        "FIDELITY). A child reading the words must see them in the picture;"
        if caption else "")
    ref = (f"\nA STYLE REFERENCE image from this SAME book is at {reference_path}. "
           f"Read it. The new image must share the SAME illustration STYLE as the "
           f"reference — the same medium and finish (soft hand-painted storybook "
           f"watercolour), the same degree of stylisation vs realism, and a similar "
           f"brushwork/linework and palette feel — so every page looks like one "
           f"artist made one cohesive book. It need NOT match the reference's "
           f"subject, pose, composition, or colours; ONLY the style must match."
           if reference_path else "")
    cohesion_reject = (
        "\n- the illustration STYLE does NOT MATCH the style reference above "
        "(a different medium, finish, or level of realism — e.g. the reference is "
        "flat and painterly but this is glossy or photoreal): the book must look "
        "stylistically cohesive page to page;" if reference_path else "")
    return f"""Read the image file at {image_path} and judge it for a character-free
children's picture book.{ref}

{_PIXELS_FIRST}This page should show: {anchor}.{scene_line}{caption_line}{focused}

This is a soft, stylised storybook. Judge GENEROUSLY on incidental variation (pose,
crop, palette, background, time of day), but be STRICT that every page shares ONE
medium and finish so the book reads as a single artist's work, and that the art
FILLS THE PAGE edge to edge. Look CLOSELY before deciding: COUNT the subject's eyes
and limbs, check that its overall BODY PLAN / SILHOUETTE is right for its real
species, scan ALL FOUR CORNERS for stray marks AND for blank white paper, and
check that the medium and finish match the rest of the book. Apply a two-tier
bar.{_STRICT_RULE}

REJECT (set ok=false) ONLY for a real defect that would break the book:
- the WRONG subject (a clearly different animal or thing than described above);
- ANY people or human figures appear (this book has no people);
- any text, letters, words, numbers, OR an artist's SIGNATURE, initials, or
  watermark are rendered in the artwork — INCLUDING faint, stylised, or scribbled
  marks tucked into a corner (the bottom corners especially);
- ANOMALOUS or UNREALISTIC ANATOMY: each animal must have anatomically CORRECT
  anatomy for its real species — the right features, the right NUMBER, AND in the
  right PLACES. Count features (eyes, legs, ears, antennae, wings, tails, eye-stalks)
  and check WHERE they sit and that NONE are extra, missing, blank, or malformed. Reject wrong counts (a snail/insect with three eyes, a mammal with
  five legs, a two-headed bird) AND misplaced features — e.g. a SNAIL's eyes are at
  the TIPS of its two upper eye-stalks, NEVER on its face/cheeks. A snail has EXACTLY
  TWO upper eye-stalks, each tipped with one eye: reject a face-eye, a THIRD or extra
  eye-stalk, or any stalk ending in a blank, eyeless bulb. Also reject malformed or distorted faces and
  extra, missing, or duplicated parts. Being "cute" does NOT excuse wrong anatomy;
- WRONG BODY PLAN / SILHOUETTE: beyond counting parts, the subject's overall body
  SHAPE must match its real species (a stylised "cute" version is fine, but the basic
  body plan must be right). Check the silhouette against these common tells:
  a RAY or skate (manta / stingray) is ONE flat, wide, diamond-shaped disc whose
  wings are PART of the body — NOT a round chubby body with separate wings stuck on,
  and NOT leg-like dangling appendages; a SHARK has an upright VERTICAL tail fin (top
  lobe taller) and gill slits — NOT a flat horizontal dolphin/whale fluke; a
  STARFISH / sea star is a FLAT star with EXACTLY FIVE arms (count them — reject a
  round dome-blob or six/seven arms); an OCTOPUS has EXACTLY EIGHT arms; a
  MANATEE / dugong has ONE large rounded PADDLE tail — NOT a forked two-lobed fish
  tail; whales, dolphins and narwhals have HORIZONTAL tail flukes and a smooth
  blowhole with NO antlers, antennae, twigs or branching sprigs growing from the head
  or blowhole; a SEAHORSE has a smooth head with NO ears and a curled prehensile
  tail; an EEL is a long, limbless, snake-like body with NO arms or legs. Reject a
  subject whose body plan is clearly wrong even when it is cute and cleanly painted;
- NOT RECOGNIZABLE AS ITS SPECIES: the animal must be clearly identifiable as the
  EXACT species named above, showing the SIGNATURE features that distinguish that
  species — not merely a generic member of that broad kind of animal. Using what you
  know about the REAL animal, REJECT if a defining feature is MISSING, smoothed away,
  or so downplayed that the subject reads as a plain, generic, or different creature —
  e.g. a PUFFERFISH drawn with a smooth body and NO spines/prickles (a real puffer is
  covered in spines when puffed), a SWORDFISH with no long sword bill, a NARWHAL with
  no tusk, a HAMMERHEAD with an ordinary head. Friendly, simplified stylisation is
  fine, but the species' signature features must be clearly present so a child could
  name the animal from the picture alone;
- EXTRA UNREQUESTED ANIMALS in the scene: this page shows the subject(s) described
  above and nothing more. REJECT if the picture adds ANIMALS or CREATURES the scene
  did NOT call for — e.g. small stray fish, birds, ducks, crabs, or other little
  creatures scattered, swimming, or floating in the BACKGROUND of a single-subject
  page. (Judge against the scene: if it describes several of one animal — "a pod of
  dolphins", "a family of penguins" — that group is fine. Incidental NON-animal
  scenery — plants, seaweed, coral, rocks, shells, bubbles, sky, water — is also fine;
  ONLY unrequested extra CREATURES are the defect.);
- a MALFORMED or HYBRID animal: anatomy that blends two species (e.g. a fox's body
  or colouring with a deer's or rabbit's tall ears/legs), mismatched or wrong body
  parts, or a creature that doesn't read clearly as ONE real animal. Every animal
  must be unmistakably a single, correct species;
- the picture looks PHOTOGRAPHIC or photorealistic — a real photo, a macro or
  close-up photograph, or a glossy 3D / CGI render — instead of a hand-painted,
  soft, simplified children's storybook illustration. It MUST clearly read as a
  storybook PAINTING (visible brushwork / drawn linework, stylised, not lifelike);
  realistic insects, fur, feathers, or water that look like a photo are a defect;
- the image looks GRAINY or NOISY: covered in fine speckle, film-grain, sensor
  noise, or a sandy/dotted texture — most visible across what should be smooth flat
  areas like open water, deep background, or sky — instead of clean, smooth painted
  watercolour washes. Soft brushwork and a few intentional bubbles are fine; an
  overall gritty, noisy, speckled finish is a defect;
- the artwork does NOT FILL THE PAGE: a band of blank white or cream PAPER — a
  border, margin, vignette, or empty background panel — surrounds the illustration
  on one or more sides or corners instead of the painted scene running full-bleed to
  all four edges. This is a print defect (uneven white margins at the trim). A soft
  painterly fade INTO colour is fine; a corner or edge of plain unpainted paper is
  not;{_PHYSICS_REJECT}{caption_reject}{cohesion_reject}

ACCEPT (set ok=true) — do NOT reject — for natural variation:
- different pose, camera angle, crop, or composition (as long as the painted art
  still fills the page edge to edge — see the blank-paper-border defect above);
- a different or simpler background, lighting, time of day, or season;
- extra incidental natural scenery (plants, sky, water) around the subject;
- loose, painterly, flat, or simplified rendering — that illustrated look is GOOD;
- stylistic differences that still read as the same soft storybook look (but NOT a
  shift in medium or finish, e.g. matte watercolour vs glossy 3D — see cohesion).

When the subject is right and the art is clean, set ok=true even if such details
differ. Reserve issues for genuine defects.{_EVIDENCE_RULE}

Return ONLY JSON: {{"ok": true|false, "issues": ["short reason", ...]}}
Output the JSON and nothing else."""


def build_describe_prompt(image_path: Path) -> str:
    """Spec-free observation pass: ask the model to report what it LITERALLY sees,
    with no idea what the picture is supposed to be. Feeding this independent
    description into the judge pass is the structural defence against the dominant
    VLM-judge failure of 'seeing' what the spec says instead of the pixels — far more
    effective than merely telling the judge to 'focus on the image'."""
    return f"""Read the image file at {image_path} and DESCRIBE exactly what you
literally see. You have NOT been told what it is supposed to be, so do not guess the
intent and do not judge quality. Report concretely:
- the main subject(s) and, COUNTING them one by one, their visible parts (eyes,
  legs, arms, fins, tails, wings, antennae, eye-stalks);
- the overall body shape / silhouette of each subject;
- what is in each of the four CORNERS and in the background;
- the medium and finish (painted, photographic, 3D, etc.) and whether the art runs
  to all four edges or leaves any blank/unpainted paper;
- any text, letters, numbers, signatures, or stray marks, and where they sit.

Just report what is in the pixels. Do NOT output a verdict or any JSON."""


# Prepended to the judge prompt when describe-then-judge is on: gives the judge an
# independent grounding to compare against the spec, while keeping the pixels final.
_OBSERVED_PREFIX = (
    "An INDEPENDENT observer, who was NOT told what this picture is meant to be, "
    "described it as follows:\n\n<observation>\n{observed}\n</observation>\n\nUse "
    "that observation to ground your check against the spec below, but rely on your "
    "OWN direct look at the image — where they differ, trust the pixels.\n\n")


def build_cover_audit_prompt(*, image_path: Path) -> str:
    return f"""Read the image file at {image_path}. It is a wraparound children's
picture-book cover laid flat: the BACK cover is the LEFT half, a thin SPINE runs
down the middle, and the FRONT cover is the RIGHT half.

{_PIXELS_FIRST}Judge it for defects a publisher would fix. REJECT (set ok=false) for
any real problem:{_STRICT_RULE}
- TEXT LEGIBILITY: any text hard to read — low contrast against the art behind it
  (e.g. pale or white text over a bright, light, or busy area), washed out, or too
  faint. The back-cover blurb must be clearly readable from its first line to its
  last; the front title and author must be clearly legible.
- TEXT PLACEMENT: text cut off, running off the page, crossing onto the wrong
  panel / over the spine, or crammed into a corner.
- BACK BLURB BALANCE: the back-cover blurb must look CENTRED and balanced within
  the back cover (the left panel). Reject if it reads as off-centre — including
  when the background behind it is lopsided (e.g. a bright pool on one side, darker
  on the other) so the text appears pushed to one side even if technically centred.
- broken or garbled text, or obvious layout breakage.
- FRONT-COVER ART DEFECTS: look CLOSELY at every illustrated animal and subject on
  the FRONT cover (the right half) — the cover art is the first thing a buyer sees,
  so be STRICT. REJECT if any subject has an obvious illustration defect, such as:
  unnatural growths, twigs, sprigs, branching coral, leaves, antennae, horns, antlers
  or stray objects sprouting from an animal's head, blowhole, back or body where they
  do not belong (e.g. a whale's blowhole must be a smooth spout, NOT a plant or branch
  growing out of its head); malformed, garbled, fused or duplicated anatomy (a wrong
  number of fins, flippers, limbs, eyes or tails; extra or merged body parts); or stray
  floating shapes that read as a rendering mistake rather than intentional scenery.
- INCONSISTENT PHYSICS on the front art: light and shadow that disagree (shadows
  falling in different directions, or a shadow with no light source), impossible
  reflections, or broken perspective / scale — machine-render tells a publisher
  would catch.

ACCEPT (set ok=true) if the front title/author and the entire back blurb are clearly
legible, the layout is clean, AND the front-cover animals are free of growths/
malformations/stray-object defects — natural art-style variation is fine.{_EVIDENCE_RULE}

Return ONLY JSON: {{"ok": true|false, "issues": ["short issue", ...]}}
Output the JSON and nothing else."""


def parse_verdict(raw: str) -> dict:
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise AuditError(f"auditor did not return valid JSON: {e}") from e
    if not isinstance(data, dict) or "ok" not in data:
        raise AuditError(f"auditor verdict missing 'ok': {data!r}")
    issues = data.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    return {"ok": bool(data["ok"]), "issues": [str(i) for i in issues]}


def _claude_vision(prompt: str) -> str:
    """Real adapter: shell to the Claude CLI in print mode (it can Read the image
    path in the prompt). Constant shell string 'claude -p' — no injection surface.

    Retries transient CLI failures (see run_claude_cli): a lone exit-1 blip on any
    of a build's hundreds of vision calls must not abort the whole run."""
    try:
        return run_claude_cli("claude -p", prompt)
    except ContentError as e:
        raise AuditError(str(e).replace("claude CLI", "claude vision")) from e


def _merge_verdicts(verdicts: list[dict], *, mode: str = "any_fail") -> dict:
    """Combine repeated audit passes; the issues are always the deduped union across
    passes (so a reroll sees every hint, even on a pass).

    mode="any_fail" (default): ok only if EVERY pass says ok. A single vision pass is
    stochastic — it caught the dolphin-tailed shark one run and missed it the next — so
    rejecting on ANY fail recovers the variance misses, at the cost of more false
    rejects ([[catch-defects-with-guards]]).

    mode="majority": ok only if a STRICT majority of passes say ok (an even split errs
    safe → reject, since this is a defect auditor). Trades some recall for precision so
    a lone over-zealous pass doesn't sink a clean page into endless rerolls."""
    n_ok = sum(1 for v in verdicts if v["ok"])
    if mode == "majority":
        ok = n_ok * 2 > len(verdicts)  # strict majority; tie → reject
    else:
        ok = n_ok == len(verdicts)     # any_fail
    issues, seen = [], set()
    for v in verdicts:
        for i in v["issues"]:
            if i not in seen:
                seen.add(i)
                issues.append(i)
    return {"ok": ok, "issues": issues}


class ClaudeVisionAuditor:
    def __init__(self, judge_fn: Callable[[str], str] | None = None,
                 passes: int = 1, aggregate: str = "any_fail",
                 describe_first: bool = False):
        self.judge_fn = judge_fn or _claude_vision
        # Number of independent vision passes per audit; >1 enables the multi-pass
        # ensemble that recovers stochastic single-pass misses. Clamp to >=1.
        self.passes = max(1, int(passes))
        # How to combine the passes: "any_fail" (max recall, default) or "majority"
        # (more precision; a lone dissent no longer triggers a reroll).
        self.aggregate = aggregate
        # Describe-then-judge: when on, one extra spec-free observation pass runs
        # first and is fed into every judge pass — the structural defence against
        # the VLM text-prior bias. Costs one extra call per audit. Default off.
        self.describe_first = describe_first

    def audit(self, image_path, *, anchor: str, reference_path=None,
              scene: str | None = None, kind: str = "character",
              caption: str | None = None) -> dict:
        if kind == "cover":
            prompt = build_cover_audit_prompt(image_path=Path(image_path))
        elif kind == "concept":
            prompt = build_concept_audit_prompt(
                anchor=anchor, scene=scene, image_path=Path(image_path),
                reference_path=Path(reference_path) if reference_path else None,
                caption=caption)
        else:
            prompt = build_audit_prompt(
                anchor=anchor, scene=scene, image_path=Path(image_path),
                reference_path=Path(reference_path) if reference_path else None)
        if self.describe_first:
            observed = self.judge_fn(build_describe_prompt(Path(image_path)))
            prompt = _OBSERVED_PREFIX.format(observed=observed.strip()) + prompt
        verdicts = [parse_verdict(self.judge_fn(prompt)) for _ in range(self.passes)]
        return _merge_verdicts(verdicts, mode=self.aggregate)
