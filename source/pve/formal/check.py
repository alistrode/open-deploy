#!/usr/bin/env python3
"""TLC checks the controller's shared transition rules; external operations remain contracts."""
import argparse,hashlib,json,pathlib,re,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]

def ts(items):return '{'+','.join(json.dumps(x) for x in sorted(items))+'}'

def generate(out,mutation=None):
    rules=json.loads((ROOT/'workflow.json').read_text())
    facts=set().union(*(set(r['requires']) for r in rules['transitions']))
    lines=[]
    for r in rules['transitions']:
        req=set(r['requires'])
        if mutation=='snapshot' and r['action']=='snapshot.done':req.discard('snapshot_verified')
        if mutation=='ownership' and r['action']=='vm.done':req.discard('vm_owned')
        lines.append(''' \\/ /\\ phase = %s
    /\\ %s \\subseteq f
    /\\ %s
    /\\ (~successOnly \\/ %s)
    /\\ phase' = %s /\\ lastFacts' = f /\\ lastHash' = h /\\ lastAction' = %s
'''%(json.dumps(r['from']),ts(req),'TRUE' if mutation=='plan' else 'h = "sealed"','FALSE' if r['action'].startswith('recover.') else 'TRUE',json.dumps(r['to']),json.dumps(r['action'])))
    source=r'''------------------- MODULE Deploy -------------------
EXTENDS Naturals, FiniteSets
CONSTANT successOnly
VARIABLES phase, lastFacts, lastHash, lastAction
vars == <<phase,lastFacts,lastHash,lastAction>>
Facts == FACTS
Init == /\ phase = "configured" /\ lastFacts = {} /\ lastHash = "sealed" /\ lastAction = "init"
Step(f,h) ==
RULES
Next == \E f \in SUBSET Facts, h \in {"sealed","changed"}: Step(f,h)
Spec == Init /\ [][Next]_vars /\ WF_vars(Next)
TypeOK == phase \in PHASES /\ lastFacts \subseteq Facts
PlanBound == lastHash = "sealed"
Ownership == lastAction \in {"vm.done","guest.done","snapshot.intent","snapshot.done","recover.intent","recover.done"} => "vm_owned" \in lastFacts
CompletionTruth == phase="complete" => {"snapshot_verified","guest_healthy","guest_bound","vm_owned"} \subseteq lastFacts
CreationBound == lastAction="vm.intent" => {"vmid_free","host_bound","inputs_verified"} \subseteq lastFacts
Completion == <>(phase="complete")
=====================================================
'''.replace('FACTS',ts(facts)).replace('PHASES',ts(rules['phases'])).replace('RULES',''.join(lines))
    (out/'Deploy.tla').write_text(source)
    cfg='SPECIFICATION Spec\nCHECK_DEADLOCK FALSE\nCONSTANT successOnly = FALSE\nINVARIANTS TypeOK PlanBound Ownership CompletionTruth CreationBound\n'
    (out/'Safety.cfg').write_text(cfg)
    (out/'Success.cfg').write_text(cfg.replace('FALSE\nINVARIANTS','TRUE\nINVARIANTS')+'PROPERTY Completion\n')


def main():
    a=argparse.ArgumentParser();a.add_argument('--jar',type=pathlib.Path,required=True);a.add_argument('--output',type=pathlib.Path,required=True);args=a.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    results=[]
    for name,mutation,cfg in [('safety',None,'Safety.cfg'),('completion',None,'Success.cfg'),('negative_snapshot','snapshot','Safety.cfg'),('negative_ownership','ownership','Safety.cfg'),('negative_plan','plan','Safety.cfg')]:
        with tempfile.TemporaryDirectory() as directory:
            p=pathlib.Path(directory);generate(p,mutation)
            r=subprocess.run(['java','-Xmx1g','-cp',str(args.jar.resolve()),'tlc2.TLC','-workers','1','-config',cfg,'Deploy.tla'],cwd=p,capture_output=True,text=True,timeout=180)
            log=r.stdout+r.stderr;(args.output/(name+'.log')).write_text(log)
            expected=('Invariant ' in log and 'is violated' in log) if mutation else 'Model checking completed. No error has been found.' in log
            result={'name':name,'expected':'counterexample' if mutation else 'pass','matched':expected,'exit_code':r.returncode}
            for pattern,key in [(r'([\d,]+) distinct states found','distinct_states'),(r'([\d,]+) states generated','states_generated')]:
                m=re.findall(pattern,log)
                if m:result[key]=int(m[-1].replace(',',''))
            print(json.dumps(result),flush=True);results.append(result)
            if not expected:raise SystemExit(log[-6000:])
    generate(args.output)
    (args.output/'results.json').write_text(json.dumps({'workflow_sha256':hashlib.sha256((ROOT/'workflow.json').read_bytes()).hexdigest(),'tlc_sha256':hashlib.sha256(args.jar.read_bytes()).hexdigest(),'scope':'Finite-state control flow with stable identity and truthful external operation results; not hardware/installer/Windows correctness','results':results},indent=2)+'\n')

if __name__=='__main__':main()
