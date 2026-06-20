"""Generate a self-contained interactive HTML "paste console" for KDP upload.

The user works KDP's upload form BY HAND, so this emits one field at a time in
KDP's entry order with a Copy-&-Next button (clipboard + a file:// fallback),
progress saved to localStorage. This is the house standard for any manual,
copy-paste deliverable — preferred over a markdown checklist. Self-contained: one
.html with inline CSS/JS, opens via file://, no build or deps."""
from __future__ import annotations
import json
from pathlib import Path
from .config import BookConfig
from .copy import book_blurb
from .checklist import _keywords
from . import specs


def _categories(cfg: BookConfig) -> str:
    if cfg.book_type == "concept":
        return ("1) Children's Books › Animals\n"
                "2) Children's Books › Science, Nature & How It Works › Nature")
    if cfg.book_type == "picture":
        return ("1) Children's Books › Growing Up & Facts of Life › Difficult "
                "Discussions › Death & Dying\n2) Children's Books › Animals")
    if cfg.book_type == "standard":
        return ("1) Self-Help › Death & Grief\n"
                "2) Family & Relationships › Death, Grief, Bereavement")
    return "1) Self-Help › Death & Grief\n2) Self-Help › Journaling"


def build_steps(cfg: BookConfig, pages: int) -> list[dict]:
    """The ordered KDP entry steps. type 'copy' = clipboard value; 'act' = do in KDP."""
    colour = cfg.book_type in ("picture", "concept")
    first, _, last = cfg.author.rpartition(" ")
    if not first:
        first, last = last, ""
    ill_first, _, ill_last = cfg.illustrator.rpartition(" ")
    if not ill_first:
        ill_first, ill_last = ill_last, ""
    spine = specs.spine_width_in(pages, specs.spine_per_page(cfg.book_type))
    royalty = specs.royalty_usd(cfg.price_usd, pages, colour=colour)
    print_cost = specs.printing_cost_usd(pages, colour=colour)
    steps = [
        {"type": "copy", "field": "Book Title", "value": cfg.title},
        {"type": "copy", "field": "Subtitle", "value": cfg.subtitle},
        {"type": "copy", "field": "Author — First name", "value": first},
        {"type": "copy", "field": "Author — Last name", "value": last},
    ]
    if cfg.illustrator:
        steps += [
            {"type": "act", "field": "Add a contributor → role: Illustrator",
             "value": "Contributors → Add → Role: Illustrator",
             "hint": "In KDP's Contributors section, add a second person with the "
                     "Illustrator role, then paste the next two fields."},
            {"type": "copy", "field": "Illustrator — First name", "value": ill_first},
            {"type": "copy", "field": "Illustrator — Last name", "value": ill_last},
        ]
    steps += [
        {"type": "copy", "field": "Description", "value": f"<p>{book_blurb(cfg)}</p>",
         "hint": "Switch the Description box to HTML view if available, then paste."},
    ]
    steps += [{"type": "copy", "field": f"Keyword {i + 1} of 7", "value": k}
              for i, k in enumerate(_keywords(cfg).split(", "))]
    steps += [
        {"type": "act", "field": "Categories (choose 2)", "value": _categories(cfg),
         "hint": "Pick via KDP's category browser — not pasteable."},
        {"type": "act", "field": "AI content disclosure",
         "value": "Text: AI-generated\nImages: AI-generated\nTranslations: None",
         "hint": "Answer when prompted. Private to Amazon."},
        {"type": "act", "field": "ISBN", "value": "Get a free KDP ISBN",
         "hint": "Free, KDP-only. Don't buy one for a KDP-only title."},
        {"type": "act", "field": "Print — Ink & paper",
         "value": ("Standard Color interior · White paper" if colour
                   else "Black & white interior · Cream paper"),
         "hint": ("⚠ Must be WHITE/colour — the spine width was computed for "
                  "white stock." if colour else
                  "⚠ Must be CREAM — the spine width was computed for cream.")},
        {"type": "act", "field": "Print — Trim size",
         "value": f"{cfg.trim_w:g} x {cfg.trim_h:g} in", "hint": "Matches the interior PDF."},
        {"type": "act", "field": "Print — Bleed", "value": "No Bleed",
         "hint": f"Interior is exactly {cfg.trim_w:g}x{cfg.trim_h:g} with margins — "
                 f"no edge-to-edge images."},
        {"type": "act", "field": "Print — Cover finish", "value": "Matte",
         "hint": "Free choice; matte suits the soft watercolour art."},
        {"type": "act", "field": "Upload interior", "value": "interior.pdf",
         "hint": f"{pages} pages. (In this book's folder.)"},
        {"type": "act", "field": "Upload cover", "value": "cover-paperback.pdf",
         "hint": f"“Upload a cover I already have.” Wraparound, spine {spine}in."},
        {"type": "act", "field": "Print Previewer", "value": "Launch & page through",
         "hint": "Confirm the cover wraps, nothing is clipped, and the back-cover blurb "
                 "clears the barcode (lower-right of the back cover)."},
        {"type": "act", "field": "Price (US)", "value": f"${cfg.price_usd:.2f}",
         "hint": f"~${royalty:.2f} royalty/sale at 60% (− ${print_cost:.2f} print)."},
    ]
    if cfg.makes_ebook:
        steps += [
            {"type": "act", "field": "Upload eBook manuscript", "value": "interior.epub",
             "hint": "Reflowable EPUB."},
            {"type": "act", "field": "Upload eBook cover", "value": "cover-ebook.jpg",
             "hint": "Front-cover JPG (no spine/back)."},
            {"type": "act", "field": "Kindle price (US)", "value": "$9.99",
             "hint": "⚠ 70% royalty ONLY in the $2.99–$9.99 band."},
        ]
    return steps


_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KDP Paste Console — __TITLE__</title>
<style>
  :root{--bg:#f6f4ef;--card:#fffdfa;--ink:#2e2a26;--muted:#7a726a;--line:#e6e0d6;
    --accent:#8a6d52;--accent2:#b08968;--done:#9aa884;--chip:#efe9df;--act:#9c6b4f}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 Georgia,serif}
  .wrap{max-width:760px;margin:0 auto;padding:18px 18px 70px}
  h1{font-size:20px;margin:0 0 3px}
  .sub{color:var(--muted);font-size:13px;margin:0 0 16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;
    box-shadow:0 2px 10px rgba(0,0,0,.04)}
  .meta{display:flex;justify-content:space-between;align-items:center;
    font:12.5px system-ui,sans-serif;color:var(--muted);margin-bottom:8px}
  .kdpfield{font:13px system-ui,sans-serif;letter-spacing:.03em;text-transform:uppercase;
    color:var(--accent);font-weight:700}
  .kind{font:11px system-ui,sans-serif;text-transform:uppercase;letter-spacing:.04em;
    padding:3px 9px;border-radius:20px}
  .kind.copy{background:#e7efe0;color:#5f7445}
  .kind.act{background:#f4e7df;color:var(--act)}
  .value{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:15px;line-height:1.5;
    background:#f3efe8;border:1px solid var(--line);border-radius:10px;padding:14px 16px;
    margin:6px 0 4px;white-space:pre-wrap;word-break:break-word;user-select:all;min-height:34px}
  .hint{color:var(--muted);font-size:13px;margin:8px 0 0}
  .btns{display:flex;gap:10px;margin-top:16px;align-items:center}
  .primary{flex:1;font:16px system-ui,sans-serif;font-weight:700;border:none;border-radius:10px;
    background:var(--accent);color:#fff;padding:14px;cursor:pointer}
  .primary:hover{background:var(--accent2)}
  .primary.copied{background:var(--done)}
  .ghost{font:13px system-ui,sans-serif;border:1px solid var(--line);background:var(--card);
    color:var(--muted);border-radius:10px;padding:14px;cursor:pointer}
  .kbd{font:11px system-ui,sans-serif;color:var(--muted);margin-top:10px;text-align:center}
  .kbd b{background:var(--chip);border-radius:4px;padding:1px 6px}
  .kbd button{font:11px system-ui,sans-serif;border:none;background:none;color:var(--accent);
    cursor:pointer;text-decoration:underline}
  .bar{height:8px;background:var(--chip);border-radius:5px;overflow:hidden;margin:14px 0 0}
  .bar>span{display:block;height:100%;width:0;
    background:linear-gradient(90deg,var(--accent2),var(--done));transition:width .25s}
  ol.list{list-style:none;margin:16px 0 0;padding:0}
  ol.list li{display:flex;gap:10px;align-items:center;padding:6px 4px;
    border-top:1px dashed var(--line);font-size:13.5px;cursor:pointer}
  ol.list li .dot{width:18px;height:18px;border-radius:50%;border:2px solid var(--line);flex:none;
    display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff}
  ol.list li.done .dot{background:var(--done);border-color:var(--done)}
  ol.list li.cur{font-weight:700;color:var(--accent)}
  ol.list li .lab{flex:1}
  ol.list li.done .lab{color:var(--muted)}
  ol.list li .mini{font:11px system-ui,sans-serif;color:var(--muted)}
</style>
</head>
<body>
<div class="wrap">
  <h1>KDP Paste Console — __TITLE__</h1>
  <p class="sub">One field at a time, in KDP's entry order. <b>Copy &amp; Next</b> copies the
  value and advances — or press <b>Enter</b>. Stay in KDP and Alt-Tab back only to advance.
  Progress is saved automatically.</p>

  <div class="card">
    <div class="meta">
      <span id="counter">—</span>
      <span class="kind copy" id="kindBadge">copy</span>
    </div>
    <div class="kdpfield" id="kdpField">—</div>
    <div class="value" id="valueBox">—</div>
    <div class="hint" id="hint"></div>
    <div class="btns">
      <button class="ghost" id="prevBtn">← Back</button>
      <button class="primary" id="copyBtn">Copy &amp; Next →</button>
    </div>
    <div class="kbd"><b>Enter</b> copy &amp; next · <b>←</b> back · <b>→</b> skip ·
      <button id="resetBtn">reset progress</button></div>
    <div class="bar"><span id="barFill"></span></div>
  </div>

  <ol class="list" id="stepList"></ol>
</div>

<script>
const SLUG = "__SLUG__";
const STEPS = __STEPS__;
const LS = "kdp-paste-" + SLUG;
let done = {};
try { done = JSON.parse(localStorage.getItem(LS) || "{}"); } catch(e) { done = {}; }
let idx = 0;
const $ = id => document.getElementById(id);

function save(){ try { localStorage.setItem(LS, JSON.stringify(done)); } catch(e){} }

function render(){
  const st = STEPS[idx];
  $('counter').textContent = `Step ${idx+1} of ${STEPS.length}`;
  const badge = $('kindBadge');
  badge.textContent = st.type==='copy' ? 'copy → paste' : 'do in KDP';
  badge.className = 'kind ' + (st.type==='copy' ? 'copy' : 'act');
  $('kdpField').textContent = st.field;
  $('valueBox').textContent = st.value;
  $('hint').textContent = st.hint || (st.type==='copy' ? 'Click Copy & Next, then paste into KDP.' : '');
  const b = $('copyBtn'); b.classList.remove('copied');
  b.innerHTML = st.type==='copy' ? 'Copy &amp; Next →' : 'Mark done →';
  $('barFill').style.width = Math.round(idx/STEPS.length*100) + '%';
  $('stepList').innerHTML = STEPS.map((s,i)=>{
    const d = done[i] ? ' done' : '', c = i===idx ? ' cur' : '';
    return `<li class="${d}${c}" data-i="${i}"><span class="dot">${done[i]?'✓':''}</span>`+
      `<span class="lab">${s.field}</span><span class="mini">${s.type==='copy'?'paste':'select'}</span></li>`;
  }).join('');
}

function copyText(t){
  if(navigator.clipboard && navigator.clipboard.writeText){
    return navigator.clipboard.writeText(t).catch(()=>fallbackCopy(t));
  }
  fallbackCopy(t); return Promise.resolve();
}
function fallbackCopy(t){
  const ta=document.createElement('textarea'); ta.value=t;
  ta.style.position='fixed'; ta.style.opacity='0';
  document.body.appendChild(ta); ta.focus(); ta.select();
  try{ document.execCommand('copy'); }catch(e){}
  document.body.removeChild(ta);
}
function advance(){ if(idx<STEPS.length-1) idx++; render(); }
function back(){ if(idx>0) idx--; render(); }
async function copyAndNext(){
  const st = STEPS[idx];
  if(st.type==='copy'){
    await copyText(st.value);
    const b=$('copyBtn'); b.classList.add('copied'); b.textContent='Copied ✓';
  }
  done[idx]=true; save();
  setTimeout(advance, st.type==='copy' ? 180 : 0);
}

$('copyBtn').addEventListener('click', copyAndNext);
$('prevBtn').addEventListener('click', back);
$('resetBtn').addEventListener('click', ()=>{ done={}; save(); idx=0; render(); });
$('stepList').addEventListener('click', e=>{
  const li=e.target.closest('[data-i]'); if(!li) return; idx=+li.dataset.i; render();
});
document.addEventListener('keydown', e=>{
  if(e.key==='Enter'){ e.preventDefault(); copyAndNext(); }
  else if(e.key==='ArrowLeft'){ e.preventDefault(); back(); }
  else if(e.key==='ArrowRight'){ e.preventDefault(); advance(); }
});
render();
</script>
</body>
</html>
"""


def make_paste_console(cfg: BookConfig, pages: int, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    steps = build_steps(cfg, pages)
    html = (_HTML
            .replace("__TITLE__", cfg.title)
            .replace("__SLUG__", cfg.slug)
            .replace("__STEPS__", json.dumps(steps)))
    out = out_dir / "paste-console.html"
    out.write_text(html, encoding="utf-8")
    return out
