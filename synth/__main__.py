import argparse
import time
from pathlib import Path

from synth.generate import generate

parser = argparse.ArgumentParser(description="Write a complete set of invented raw exports for the sample household.")
parser.add_argument("--out", default="data", help="destination folder (default: data/)")
parser.add_argument("--seed", type=int, default=20260912)
args = parser.parse_args()
t0 = time.time()
summary = generate(Path(args.out), args.seed)
print(f"wrote {args.out}/ in {time.time() - t0:.1f}s")
for k, v in summary.items():
    print(f"  {k}: {v}")
