"""Regenerate the rules-only hand/foot coordination comparison (no ML)."""
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from boulderlab.own_routes import generate_study
if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=60)
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/own-routes-study')
    args=parser.parse_args()
    if not 5 <= args.seconds <= 60: parser.error('seconds must be 5–60 per route')
    generate_study(args.output,args.seconds)
