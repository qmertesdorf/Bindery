# *Where Does Mango Go?* — Comfort Theme + Cast Page Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the picture-book pipeline to support a comforting "where do pets go" theme via a `theme` config field and an honest `cast` page model (`child` / `child_and_pet` / `pet`) that replaces the time-based `moment` field, then wire the new book *Where Does Mango Go?* (Posy + cat Mango) — all fakes-tested, no GPU.

**Architecture:** Add a guarded `theme` enum to `BookConfig`. Replace the page `moment` (`memory|present`) with `cast` (`child|child_and_pet|pet`) across content generation, validation, and `flux_art` LoRA routing — adding a new `pet` cast that renders the companion LoRA alone (the peaceful-place pages) and audits against a pet-only anchor. Make the content prompts theme-aware (grief default, comfort new). The shipped dog book renders identically under `cast`.

**Tech Stack:** Python 3.11, pytest, frozen dataclasses, ComfyUI HTTP API (faked in tests).

**Scope:** This plan is **piece A** of the spec (`docs/superpowers/specs/2026-06-14-where-does-mango-go-design.md`) — the code engine + book config. **Piece B (training the `posy` + `mango` LoRAs) is the spec's GPU runbook and is NOT in this plan.** The config names the expected LoRA filenames (`posy_flux.safetensors`, `mango_flux.safetensors`); a real GPU build waits on piece B, but everything here is fakes-tested and lands independently.

---

## How to run tests (read first — non-obvious)

- **Always run from `C:\Users\quint\git\book-gen\factory`** (where `pyproject.toml` lives), using the **project venv python**:
  `./.venv/Scripts/python.exe -m pytest -q`
- Do NOT use the global `python` (missing `ebooklib` → collection errors). Do NOT run from `factory/factory/` (its `copy.py` shadows stdlib `copy`).
- Single file: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
- Baseline before this plan: **139 passing.** Work on a branch (`feat/comfort-picture-book` already exists). There is unrelated uncommitted scratch work in the tree — only `git add` the exact files each task changes.

## File Structure

- `factory/factory/config.py` — **modify.** Add a `theme` field + picture validation.
- `factory/factory/picture_content.py` — **modify.** Validate `cast` (not `moment`); make `build_bible_prompt`/`build_story_prompt` theme-aware (grief keeps behavior; comfort is new and emits all three casts).
- `factory/factory/flux_art.py` — **modify.** `page_plan` routes on `cast` (3 branches incl. a child-free `pet` branch); `generate_flux_art` computes a `pet_anchor` and selects the audit anchor by cast.
- `factory/books/where-does-mango-go.config.json` — **create.** The comfort book config.
- `factory/tests/conftest.py`, `tests/test_picture_content.py`, `tests/test_flux_art.py`, `tests/test_config.py` — **modify** (the `moment`→`cast` rename + new coverage).
- `build.py` is **untouched** — the `art_engine == "flux"` route already exists; the cast model is internal to `flux_art`/`picture_content`.

---

### Task 1: Add the `theme` config field + validation

**Files:**
- Modify: `factory/factory/config.py`
- Test: `factory/tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `factory/tests/test_config.py` (the helper `_write_d(tmp_path, d)` and imports already exist):

```python
def test_picture_theme_defaults_to_grief(tmp_path):
    cfg = load_config(_write_d(tmp_path, {
        "slug": "k", "title": "T", "subtitle": "S", "author": "A", "art_prompt": "x",
        "book_type": "picture", "pet_kind": "dog", "pet_name": "Sunny",
        "page_count": 22}))
    assert cfg.theme == "grief"

def test_picture_theme_comfort_parses(tmp_path):
    cfg = load_config(_write_d(tmp_path, {
        "slug": "k", "title": "T", "subtitle": "S", "author": "A", "art_prompt": "x",
        "book_type": "picture", "pet_kind": "cat", "pet_name": "Mango",
        "page_count": 22, "theme": "comfort"}))
    assert cfg.theme == "comfort"

def test_invalid_theme_rejected(tmp_path):
    with pytest.raises(ConfigError, match="theme"):
        load_config(_write_d(tmp_path, {
            "slug": "k", "title": "T", "subtitle": "S", "author": "A", "art_prompt": "x",
            "book_type": "picture", "pet_kind": "cat", "pet_name": "Mango",
            "page_count": 22, "theme": "spooky"}))
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -k theme -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'theme'` or AttributeError on `cfg.theme`.

- [ ] **Step 3: Add the `theme` field to `BookConfig`**

In `factory/factory/config.py`, after the `characters: tuple = ()` field (config.py:51) add:

```python
    theme: str = "grief"                  # picture only — content arc: "grief" or "comfort"
```

- [ ] **Step 4: Parse + validate `theme` in `load_config`**

In `factory/factory/config.py`, after the `art_engine = str(data.get("art_engine", "sdxl"))` line (config.py:74) add:

```python
    theme = str(data.get("theme", "grief"))
```

Inside the `if book_type == "picture":` block, immediately after the `page_count` check (the block ending `...got {pc}")`, config.py:95) and before the `if art_engine not in (...)` check, add:

```python
        if theme not in ("grief", "comfort"):
            raise ConfigError(
                f"{path}: picture 'theme' must be 'grief' or 'comfort', "
                f"got {theme!r}")
```

Then in the `return BookConfig(...)` call, after the `characters=tuple(...)` argument (config.py:146) add:

```python
        theme=theme,
```

- [ ] **Step 5: Run to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: PASS (all existing config tests + 3 new theme tests).

- [ ] **Step 6: Commit**

```bash
git add factory/factory/config.py factory/tests/test_config.py
git commit -m "feat(config): picture theme field (grief|comfort) with guard"
```

---

### Task 2: Replace `moment` with the `cast` page model (incl. the `pet` cast)

This is a cross-cutting rename + feature; it must land together to keep the suite green. `cast ∈ {child, child_and_pet, pet}` directly drives LoRA selection. `child_and_pet`/`child` preserve today's two behaviors; `pet` is new (companion alone).

**Files:**
- Modify: `factory/factory/picture_content.py`, `factory/factory/flux_art.py`
- Modify (test data + assertions): `factory/tests/conftest.py`, `tests/test_picture_content.py`, `tests/test_flux_art.py`

- [ ] **Step 1: Update the failing tests first — `test_picture_content.py`**

In `factory/tests/test_picture_content.py`, replace the `_page` helper (lines 14-16) with:

```python
def _page(i):
    return {"text": f"line {i}", "scene": f"scene {i}",
            "cast": "child_and_pet" if i % 2 else "child", "mood": "tender"}
```

Replace `test_validate_story_rejects_bad_moment` (lines 35-38) with:

```python
def test_validate_story_rejects_bad_cast():
    pages = [{"text": "t", "scene": "s", "cast": "flashback", "mood": "sad"}] * 4
    with pytest.raises(ContentError, match="cast"):
        validate_story({"pages": pages, "closing": "c"}, 4)
```

In `test_validate_story_rejects_empty_scene` (lines 30-33) change the page dict's `"moment": "present"` to `"cast": "child"`. In `test_validate_story_rejects_missing_mood` (lines 40-43) change `"moment": "present"` to `"cast": "child"`. In `test_generate_picture_content_assembles_schema` (line 56) change the final assertion to:

```python
    assert out["pages"][0]["cast"] in ("child", "child_and_pet", "pet")
```

- [ ] **Step 2: Update the failing tests — `test_flux_art.py`**

In `factory/tests/test_flux_art.py`, update the three `page_plan` tests and `_flux_content`, and add `pet`-cast coverage. Replace `test_page_plan_memory_uses_both_loras_and_dog_trigger`, `test_page_plan_present_uses_hero_only_and_excludes_animals`, and `test_page_plan_no_companion_treats_memory_as_hero_only` (lines 16-40) with:

```python
def test_page_plan_child_and_pet_uses_both_loras_and_triggers():
    page = {"scene": "a sunny field", "cast": "child_and_pet", "mood": "happy"}
    prompt, loras = page_plan(page, hero=HERO, companion=DOG,
                              style="watercolour", outfit="a red sweater")
    assert loras == [("boy.safetensors", 0.9), ("dog.safetensors", 0.85)]
    assert "b1scuitboy boy" in prompt and "b1scuitdog dog" in prompt
    assert "a red sweater" in prompt
    assert "warm gentle smile" in prompt          # happy mood -> smiling

def test_page_plan_child_uses_hero_only_and_excludes_animals():
    page = {"scene": "an empty hallway", "cast": "child", "mood": "sad"}
    prompt, loras = page_plan(page, hero=HERO, companion=DOG,
                              style="watercolour", outfit="a red sweater")
    assert loras == [("boy.safetensors", 0.9)]
    assert "b1scuitdog dog" not in prompt
    assert "no animals" in prompt
    assert "not smiling" in prompt                # sad mood (in GRIEF) -> no smile

def test_page_plan_no_companion_treats_child_and_pet_as_hero_only():
    page = {"scene": "a field", "cast": "child_and_pet", "mood": "happy"}
    prompt, loras = page_plan(page, hero=HERO, companion=None,
                              style="w", outfit="o")
    assert loras == [("boy.safetensors", 0.9)]

def test_page_plan_pet_renders_companion_alone():
    page = {"scene": "a luminous meadow", "cast": "pet", "mood": "peaceful"}
    prompt, loras = page_plan(page, hero=HERO, companion=DOG,
                              style="watercolour", outfit="a red sweater")
    assert loras == [("dog.safetensors", 0.85)]      # companion only
    assert "b1scuitdog dog" in prompt
    assert "b1scuitboy boy" not in prompt            # no child
    assert "a red sweater" not in prompt             # no outfit (no child)
    assert "No people" in prompt
```

In `_flux_content` (lines 84-91) change the two page dicts' `"moment": "memory"` → `"cast": "child_and_pet"` and `"moment": "present"` → `"cast": "child"`. Add a new test after `test_generate_flux_art_audits_present_page_against_boy_only_anchor`:

```python
def test_generate_flux_art_audits_pet_page_against_pet_only_anchor(tmp_path):
    content = {"character_anchor": "a little girl Posy. Mango is a ginger tabby cat",
               "art_style": "soft watercolour", "dedication": "d",
               "pages": [{"text": "t", "scene": "a meadow", "cast": "pet",
                          "mood": "peaceful"}],
               "closing": "c"}
    cfg = BookConfig(slug="k", title="T", subtitle="S", author="A",
                     art_prompt="cover", book_type="picture", pet_kind="cat",
                     pet_name="Mango", page_count=4, trim_w=8.5, trim_h=8.5,
                     art_engine="flux", flux_style="ws", flux_guidance=2.4,
                     outfit="a blue dress", characters=(
                         Character(role="hero", lora="posy.safetensors",
                                   trigger="p0sygirl girl"),
                         Character(role="companion", lora="mango.safetensors",
                                   trigger="mang0cat cat", strength=0.85)))
    aud = _Auditor()
    generate_flux_art(cfg, content, tmp_path, _fake_comfy(), seed=7, auditor=aud)
    # the pet page audits against the pet's part of the anchor, not the child's
    assert "ginger tabby" in aud.anchors[0]
    assert "Posy" not in aud.anchors[0]
```

- [ ] **Step 3: Update the shared fixture — `conftest.py`**

In `factory/tests/conftest.py`, in the `picture_content` fixture, change the page `moment` keys to `cast` (memory→child_and_pet, present→child). Replace the `_pages` assignment with:

```python
    _pages = (
        [{"text": "We walked every morning, Sunny and me.", "scene": "garden path at dawn",
          "cast": "child_and_pet", "mood": "happy"},
         {"text": "Now the leash hangs still by the door.", "scene": "quiet hallway, leash on a hook",
          "cast": "child", "mood": "sad"}]
        + [{"text": f"I remember you, page {i}.", "scene": f"memory scene {i}",
            "cast": "child_and_pet" if i % 2 else "child", "mood": "wistful"}
           for i in range(3, 21)]
    )
```

- [ ] **Step 4: Run to verify the new tests fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_picture_content.py tests/test_flux_art.py -q`
Expected: FAIL — `validate_story` still rejects on `moment`/accepts only `memory|present`; `page_plan` still reads `moment`; the `pet` tests have no behavior yet.

- [ ] **Step 5: Update `validate_story` to require `cast` — `picture_content.py`**

In `factory/factory/picture_content.py`, replace the moment check in `validate_story` (lines 85-87) with:

```python
        if str(pg.get("cast", "")).strip() not in ("child", "child_and_pet", "pet"):
            raise ContentError(
                f"story page {i} 'cast' must be 'child', 'child_and_pet', or 'pet'")
```

- [ ] **Step 6: Update the grief story prompt to emit `cast` — `picture_content.py`**

In `factory/factory/picture_content.py`, replace the entire `build_story_prompt` function (lines 26-61) with this cast-based grief version (theme branching is added in Task 3):

```python
def build_story_prompt(cfg: BookConfig, anchor: str) -> str:
    return f"""You are writing the gentle children's picture book "{cfg.title}" for a
child (ages 4-8) whose {cfg.pet_kind}, {cfg.pet_name}, has died. The child narrates.
Warm, simple, honest, never clinical; never the "Rainbow Bridge" poem.

The recurring characters (keep every page consistent with this): {anchor}

This is a grief book. {cfg.pet_name} is GONE. Structure the {cfg.page_count} pages as
a gentle arc: a few happy MEMORIES of {cfg.pet_name} alive → the loss and the empty
home → missing {cfg.pet_name}, sad and comforted (sometimes by a parent, or looking
at a photo) → slowly remembering with love and quiet hope.

Return ONLY valid JSON:
{{"pages": [{{"text": "...", "cast": "child|child_and_pet", "mood": "...",
            "scene": "..."}}], "closing": "..."}}
- "text": 1-2 short child-friendly sentences for the page.
- "cast": who is in THIS page's PICTURE — "child_and_pet" for a happy flashback when
  {cfg.pet_name} was alive (the child AND {cfg.pet_name} together); "child" for now,
  after the loss (the child ALONE). A grief book uses only these two.
- "mood": the child's feeling on this page (e.g. happy, playful, tender, sad,
  lonely, wistful, comforted, hopeful) — vary it honestly with the cast.
- "scene": a RICH, concrete visual description — the SETTING (a real place: a
  sunlit park, a cozy living room with furniture, a bedroom at dusk), what the
  child is doing, and the child's expression matching the mood.
  CRITICAL constraints (an image model can only reliably draw the child alone, or
  the child with the {cfg.pet_kind}):
  * The picture shows ONLY the child — never any other PEOPLE (no parent, no
    friends); a parent's comfort belongs in the "text", not the picture.
  * On a "child" page the scene must show ONLY the child in a setting with an
    expression matching the mood, and must NOT mention or depict {cfg.pet_name},
    the {cfg.pet_kind}, a photo/picture of it, or its bed/leash/toys — naming the
    animal makes the image model draw a live one. The loss is carried by the
    "text", not the picture.
  * Only "child_and_pet" pages show {cfg.pet_name} (alive, with the child).
  Keep objects simple. No words/letters in the picture.
- "closing": one comforting closing line for the final page.
Exactly {cfg.page_count} page objects. Output the JSON and nothing else."""
```

- [ ] **Step 7: Rewrite `page_plan` to route on `cast` — `flux_art.py`**

In `factory/factory/flux_art.py`, replace the entire `page_plan` function (lines 80-99) with:

```python
def page_plan(page: dict, *, hero, companion, style: str, outfit: str):
    """Return (prompt, loras) for a page. The page's `cast` selects who is in
    frame and which LoRAs render: "child_and_pet" stacks both LoRAs and names both
    triggers; "pet" renders the companion alone (a peaceful "where pets go" scene,
    no child); "child" (default) is the hero alone with animals excluded so the
    model never invents a live pet."""
    mood = page.get("mood", "tender")
    expr = _expression(mood)
    cast = page.get("cast", "child")
    tail = "Richly detailed background, illustrated edge to edge."
    if cast == "child_and_pet" and companion is not None:
        loras = [(hero.lora, hero.strength), (companion.lora, companion.strength)]
        prompt = (f"{style}. {hero.trigger} {outfit}, together with "
                  f"{companion.trigger}. {page['scene']} The child shows {expr}, "
                  f"clearly {mood}. Only the child and the pet, no other people. "
                  f"{tail}")
    elif cast == "pet" and companion is not None:
        loras = [(companion.lora, companion.strength)]
        prompt = (f"{style}. {companion.trigger}, peaceful and content, in "
                  f"{page['scene']} No people, no other animals. Soft luminous "
                  f"light. {tail}")
    else:
        loras = [(hero.lora, hero.strength)]
        prompt = (f"{style}. {hero.trigger} {outfit}, alone, no other people, no "
                  f"animals. {page['scene']} The child shows {expr}, clearly "
                  f"{mood}. {tail}")
    return prompt, loras
```

- [ ] **Step 8: Add `pet_anchor` + cast-based audit anchor in `generate_flux_art` — `flux_art.py`**

In `factory/factory/flux_art.py`, after the `hero_anchor = (...)` assignment (lines 119-122) add:

```python
    # For "pet"-cast pages (the companion alone), audit against just the pet's part
    # of the anchor (the pet name onward) so the auditor doesn't demand the child.
    pet_anchor = (pet + anchor.split(pet, 1)[1].rstrip() if pet and pet in anchor
                  else anchor)
```

Then replace the per-page `memory`/`audit_anchor`/`_log` lines (lines 130-133) with:

```python
        cast = page.get("cast", "child")
        audit_anchor = {"child_and_pet": anchor, "pet": pet_anchor}.get(
            cast, hero_anchor)
        _log(f"[flux] page {i}/{n} ({cast},{page.get('mood')}): "
             f"{page['scene'][:60]}")
```

- [ ] **Step 9: Run the full suite to verify green**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS — all picture-content, flux-art, build, and config tests green (the `moment`→`cast` rename is complete; new `pet` tests pass). Count ≈ **144 passing** (139 baseline + 3 from Task 1 + 2 net new here: the renamed tests replace old ones, plus the pet `page_plan` and pet-anchor tests). Zero failures. (Note: mid-task — after the test edits in Steps 1–3 but before the implementation in Steps 5–8 — the suite is intentionally RED; green is restored at this step.)

- [ ] **Step 10: Commit**

```bash
git add factory/factory/picture_content.py factory/factory/flux_art.py \
  factory/tests/conftest.py factory/tests/test_picture_content.py \
  factory/tests/test_flux_art.py
git commit -m "feat(picture): cast page model (child|child_and_pet|pet) replaces moment"
```

---

### Task 3: Theme-aware content prompts (comfort arc)

**Files:**
- Modify: `factory/factory/picture_content.py`
- Test: `factory/tests/test_picture_content.py`

- [ ] **Step 1: Write the failing tests**

Append to `factory/tests/test_picture_content.py`:

```python
def test_comfort_story_prompt_uses_all_three_casts_and_frame():
    p = build_story_prompt(_cfg(theme="comfort"), anchor="a girl and a cat")
    assert "child_and_pet" in p and "pet" in p and "child" in p
    assert "peaceful" in p.lower()           # the luminous "beyond" framing
    assert "heart" in p.lower()              # closes on "stays in your heart"
    assert "GONE" not in p                   # not the grief framing

def test_grief_story_prompt_still_grief_by_default():
    p = build_story_prompt(_cfg(), anchor="a child and a dog")   # theme defaults grief
    assert "GONE" in p and "grief book" in p

def test_comfort_bible_prompt_framing():
    p = build_bible_prompt(_cfg(theme="comfort"))
    assert "Sunny" in p and "comfort" in p.lower()
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_picture_content.py -k "comfort or still_grief" -v`
Expected: FAIL — the comfort prompt branch doesn't exist; `build_story_prompt` always emits the grief text (no "pet" cast, no "heart").

- [ ] **Step 3: Make `build_story_prompt` dispatch on theme; add the comfort body**

In `factory/factory/picture_content.py`, rename the current `build_story_prompt` body into `_grief_story_prompt` and add a `_comfort_story_prompt` plus a dispatcher. Replace the whole `build_story_prompt` function (the Task 2 version) with these three functions:

```python
def build_story_prompt(cfg: BookConfig, anchor: str) -> str:
    if cfg.theme == "comfort":
        return _comfort_story_prompt(cfg, anchor)
    return _grief_story_prompt(cfg, anchor)


def _grief_story_prompt(cfg: BookConfig, anchor: str) -> str:
    return f"""You are writing the gentle children's picture book "{cfg.title}" for a
child (ages 4-8) whose {cfg.pet_kind}, {cfg.pet_name}, has died. The child narrates.
Warm, simple, honest, never clinical; never the "Rainbow Bridge" poem.

The recurring characters (keep every page consistent with this): {anchor}

This is a grief book. {cfg.pet_name} is GONE. Structure the {cfg.page_count} pages as
a gentle arc: a few happy MEMORIES of {cfg.pet_name} alive → the loss and the empty
home → missing {cfg.pet_name}, sad and comforted (sometimes by a parent, or looking
at a photo) → slowly remembering with love and quiet hope.

Return ONLY valid JSON:
{{"pages": [{{"text": "...", "cast": "child|child_and_pet", "mood": "...",
            "scene": "..."}}], "closing": "..."}}
- "text": 1-2 short child-friendly sentences for the page.
- "cast": who is in THIS page's PICTURE — "child_and_pet" for a happy flashback when
  {cfg.pet_name} was alive (the child AND {cfg.pet_name} together); "child" for now,
  after the loss (the child ALONE). A grief book uses only these two.
- "mood": the child's feeling on this page (e.g. happy, playful, tender, sad,
  lonely, wistful, comforted, hopeful) — vary it honestly with the cast.
- "scene": a RICH, concrete visual description — the SETTING (a real place: a
  sunlit park, a cozy living room with furniture, a bedroom at dusk), what the
  child is doing, and the child's expression matching the mood.
  CRITICAL constraints (an image model can only reliably draw the child alone, or
  the child with the {cfg.pet_kind}):
  * The picture shows ONLY the child — never any other PEOPLE (no parent, no
    friends); a parent's comfort belongs in the "text", not the picture.
  * On a "child" page the scene must show ONLY the child in a setting with an
    expression matching the mood, and must NOT mention or depict {cfg.pet_name},
    the {cfg.pet_kind}, a photo/picture of it, or its bed/leash/toys — naming the
    animal makes the image model draw a live one. The loss is carried by the
    "text", not the picture.
  * Only "child_and_pet" pages show {cfg.pet_name} (alive, with the child).
  Keep objects simple. No words/letters in the picture.
- "closing": one comforting closing line for the final page.
Exactly {cfg.page_count} page objects. Output the JSON and nothing else."""


def _comfort_story_prompt(cfg: BookConfig, anchor: str) -> str:
    return f"""You are writing the gentle, comforting children's picture book
"{cfg.title}" for a child (ages 4-8) whose {cfg.pet_kind}, {cfg.pet_name}, has died.
The child narrates. Warm, simple, honest, reassuring; never the "Rainbow Bridge"
poem; no religious afterlife claims.

The recurring characters (keep every page consistent with this): {anchor}

This is a COMFORT book answering a child's question: "where did {cfg.pet_name} go?"
Structure the {cfg.page_count} pages as a gentle arc: the child misses {cfg.pet_name}
(alone) → wonders where {cfg.pet_name} went → gentle, dreamlike VISIONS of
{cfg.pet_name} safe and at peace in a luminous natural place (sunlit meadows, soft
warm light, drifting stars) — sometimes {cfg.pet_name} alone, sometimes the child
imagining herself THERE with {cfg.pet_name} → reassurance that {cfg.pet_name} is
happy and safe → close on the comforting truth that {cfg.pet_name} stays in your
HEART, in love and memory and the warm world around us.

Return ONLY valid JSON:
{{"pages": [{{"text": "...", "cast": "child|child_and_pet|pet", "mood": "...",
            "scene": "..."}}], "closing": "..."}}
- "text": 1-2 short child-friendly sentences for the page.
- "cast": who is in THIS page's PICTURE —
  * "child": the child ALONE (missing {cfg.pet_name}, wondering, or held in a warm
    quiet moment of "they stay in your heart").
  * "pet": {cfg.pet_name} ALONE, peaceful and content, in the luminous place — no
    people at all. Use these for the "where {cfg.pet_name} is now" visions.
  * "child_and_pet": the child AND {cfg.pet_name} together in that gentle place
    (the child imagining herself there with {cfg.pet_name}).
- "mood": the feeling on this page (e.g. wondering, wistful, gentle, peaceful,
  tender, comforted, hopeful, warm) — vary it honestly with the cast.
- "scene": a RICH, concrete visual — the SETTING and the subject's expression.
  CRITICAL constraints (an image model can only reliably draw the child alone, the
  child with {cfg.pet_name}, or {cfg.pet_name} alone):
  * NEVER any other PEOPLE (no parent, no friends).
  * On a "child" page show ONLY the child; do NOT depict {cfg.pet_name}.
  * On a "pet" page show ONLY {cfg.pet_name} in the luminous place; NO people.
  * On a "child_and_pet" page show the child and {cfg.pet_name} together.
  Keep objects simple. No words/letters in the picture.
- "closing": one comforting closing line about {cfg.pet_name} staying in your heart.
Exactly {cfg.page_count} page objects. Output the JSON and nothing else."""
```

- [ ] **Step 4: Make `build_bible_prompt` theme-aware**

In `factory/factory/picture_content.py`, replace the first line of `build_bible_prompt`'s returned string (the premise sentence, lines 10-12) so the framing depends on theme. Replace the entire `build_bible_prompt` function (lines 9-23) with:

```python
def build_bible_prompt(cfg: BookConfig) -> str:
    premise = (
        f"a gentle, comforting children's picture book that reassures a young child "
        f"(ages 4-8) about where their {cfg.pet_kind}, named {cfg.pet_name}, has gone"
        if cfg.theme == "comfort" else
        f"a gentle children's picture book for a young child (ages 4-8) grieving the "
        f"death of their {cfg.pet_kind}, named {cfg.pet_name}")
    return f"""You are designing {premise}. The child narrates; {cfg.pet_name} appears
in soft, tender moments. Title: {cfg.title}.

First produce the STORY BIBLE. Return ONLY valid JSON (no markdown, no commentary):
{{"character_anchor": "...", "art_style": "...", "dedication": "..."}}
- "character_anchor": a SIMPLE, ICONIC, fixed visual description reused on every
  page so an image model can repeat it — the child (age, hair, skin, ONE simple
  outfit) and {cfg.pet_name} the {cfg.pet_kind} (breed, colour, markings). Keep it
  concrete and free of scene details. No proper nouns an image model can't draw.
- "art_style": one short style string, e.g.
  "soft flat storybook watercolor, muted palette, soft edges, no text".
- "dedication": one tender line for the dedication page.
Output the JSON and nothing else."""
```

Note: this keeps the existing `test_bible_prompt_mentions_pet_name_and_audience` passing (grief default still says "grieving"; the pet name and "dog" still appear).

- [ ] **Step 5: Run to verify all pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_picture_content.py -v`
Expected: PASS — comfort + grief prompt tests green, existing content tests unaffected.

- [ ] **Step 6: Commit**

```bash
git add factory/factory/picture_content.py factory/tests/test_picture_content.py
git commit -m "feat(picture): theme-aware content prompts (comfort where-pets-go arc)"
```

---

### Task 4: Wire the *Where Does Mango Go?* book config

**Files:**
- Create: `factory/books/where-does-mango-go.config.json`
- Test: `factory/tests/test_config.py`

- [ ] **Step 1: Write the failing validity test**

Append to `factory/tests/test_config.py` (the `Path` import already exists near the bottom of the file):

```python
def test_where_does_mango_go_config_is_valid():
    p = Path(__file__).resolve().parent.parent / "books" / "where-does-mango-go.config.json"
    cfg = load_config(p)
    assert cfg.book_type == "picture" and cfg.art_engine == "flux"
    assert cfg.theme == "comfort" and cfg.pet_name == "Mango"
    assert cfg.trim_w == 8.5 and cfg.page_count >= 20 and cfg.page_count % 2 == 0
    assert len(cfg.characters) == 2
    assert cfg.characters[0].role == "hero"
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -k mango -v`
Expected: FAIL — `ConfigError: ... invalid JSON` / file-not-found (the config doesn't exist yet).

- [ ] **Step 3: Create the book config**

Create `factory/books/where-does-mango-go.config.json` with exactly:

```json
{
  "slug": "where-does-mango-go",
  "book_type": "picture",
  "art_engine": "flux",
  "theme": "comfort",
  "title": "Where Does Mango Go?",
  "subtitle": "A Gentle Story About Where Beloved Pets Go",
  "author": "Eleanor Hartley",
  "pet_kind": "cat",
  "pet_name": "Mango",
  "page_count": 22,
  "flux_style": "Loose hand-painted watercolour storybook illustration, wet-on-wet washes with soft bleeding edges and gentle visible brushwork, pale muted palette, soft white space, delicate, dreamy and tender, minimal linework, textured watercolour paper, children's picture book art, no text",
  "flux_guidance": 2.4,
  "outfit": "wearing a soft sky-blue pinafore dress over a cream long-sleeved top and little red shoes",
  "character_anchor": "A round-faced little blonde girl about five years old with fair skin and shoulder-length wavy honey-blonde hair with a small side braid, wearing a soft sky-blue pinafore dress over a cream long-sleeved top and little red shoes. Mango is a small soft ginger and orange tabby cat with a cream chest and paws, gentle amber-green eyes, a fluffy tail, and a little pink nose.",
  "characters": [
    {"role": "hero", "lora": "posy_flux.safetensors", "trigger": "p0sygirl girl", "strength": 0.9},
    {"role": "companion", "lora": "mango_flux.safetensors", "trigger": "mang0cat cat", "strength": 0.85, "appears_on": "all"}
  ],
  "art_prompt": "soft storybook watercolour front cover, a little blonde girl and a gentle ginger tabby cat sitting close together on a sunlit grassy hill at golden hour, warm and hopeful, soft glowing light, no text, no words",
  "trim_w": 8.5,
  "trim_h": 8.5,
  "price_usd": 10.99,
  "blurb": "When a beloved cat is gone, a child's first question is the biggest one: where did they go? Through a little girl's eyes and soft, glowing watercolours, this gentle reassurance carries a family from missing Mango toward a tender, comforting answer — that those we love are safe, at peace, and always close in our hearts. A soothing read-aloud and a caring gift for any child saying goodbye to a cherished pet."
}
```

Note: `posy_flux.safetensors` / `mango_flux.safetensors` are the **expected** LoRA filenames; piece B (training) produces them, after which confirm/adjust the names + strengths here. The config is valid and loadable now (the names just have to be non-empty for the flux guard).

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -k mango -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (≈148: ~144 after Task 2 + 3 comfort-prompt tests in Task 3 + 1 here). Zero failures.

- [ ] **Step 6: Commit**

```bash
git add factory/books/where-does-mango-go.config.json factory/tests/test_config.py
git commit -m "feat(book): add Where Does Mango Go? comfort picture config"
```

---

## Notes for the implementer

- **Run pytest from `factory/` with `./.venv/Scripts/python.exe -m pytest`** — not the global python, not from `factory/factory/`.
- **`build.py` is intentionally untouched** — the flux route and the build flow already handle picture books; the cast model is internal to `flux_art`/`picture_content`.
- **The dog book (*The Morning Walk*) is not edited** and renders identically: its grief content now emits `cast` (`child_and_pet`/`child`) instead of `moment`, which maps 1:1 onto the old LoRA selection.
- **LoRA training (piece B) is out of scope** — a real GPU build of this book waits on the `posy`/`mango` LoRAs existing in `ComfyUI/models/loras`. Everything in this plan is fakes-tested.
- **Comfort-arc art quality** (especially the `pet`-alone luminous pages and the lightly-generalized prompt wording) can only be confirmed visually on a real GPU build.
```