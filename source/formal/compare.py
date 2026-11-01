#!/usr/bin/env python3
"""Compare exhaustive Go reducer reachability with the independent TLC projection."""
import argparse,hashlib,json,pathlib
p=argparse.ArgumentParser();p.add_argument('--go',type=pathlib.Path,required=True);p.add_argument('--evidence',type=pathlib.Path,required=True);a=p.parse_args()
keys=('phase','activations','attempts','proofs')
def states(path):return {tuple(s[k] for k in keys) for s in json.loads(path.read_text())}
g=states(a.go);t=states(a.evidence/'tlc-projection.json')
if g!=t:raise SystemExit(f'Refinement projection mismatch: Go-only {g-t}; TLC-only {t-g}')
projection=[dict(zip(keys,s)) for s in sorted(g)]
(a.evidence/'go-projection.json').write_text(json.dumps(projection,indent=2)+'\n')
report={'equal':True,'projected_states':len(g),'keys':keys,'workflow_sha256':hashlib.sha256((pathlib.Path(__file__).parent.parent/'src/workflow.json').read_bytes()).hexdigest(),'scope':'equality of reachable control-state projections; external operations are contracts, not verified implementations'}
(a.evidence/'refinement.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
