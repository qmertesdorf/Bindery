"""Persistent VQAScore worker — runs INSIDE the isolated GPU venv
(~/.book-gen-vqa), NOT factory/.venv. Loads a t2v_metrics VQAScore model once,
then serves scores over a line-oriented stdin/stdout JSON protocol so the build
loop pays the (slow) model-load cost only once.

Standalone by design: imports only t2v_metrics + stdlib, never `factory`, so it
runs under an interpreter that has torch but not this package. Protocol:
  parent -> worker (stdin) : {"image": "<path>", "caption": "<text>"}\n
  worker -> parent (stdout): {"score": <float>}\n   or  {"error": "<msg>"}\n
A single {"ready": true} line is emitted on stdout once the model has loaded.
All model/library chatter goes to stderr to keep stdout a clean response channel.
"""
import argparse
import json
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="clip-flant5-xl")
    args = ap.parse_args()

    import t2v_metrics  # heavy; loads torch + the VQA model
    model = t2v_metrics.VQAScore(model=args.model)

    # Signal readiness AFTER the slow load so the parent can block on this line.
    sys.stdout.write(json.dumps({"ready": True}) + "\n")
    sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            score = model(images=[req["image"]], texts=[req["caption"]])
            val = float(score.item() if hasattr(score, "item") else score[0][0])
            out = {"score": val}
        except Exception as e:  # never die on one bad request; report and continue
            out = {"error": str(e)}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
