#!/usr/bin/env python3
"""Independent TLC model checking of the exact transition manifest embedded by Go.
No hardware-success claim follows from this abstraction; see README.md.
"""
import argparse,hashlib,json,pathlib,re,subprocess,tempfile,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
DEFINITION=ROOT/'src/workflow.json'

def tla_set(items):return '{'+', '.join(json.dumps(s) for s in items)+'}'
def generate(directory,mutant=None):
 d=json.loads(DEFINITION.read_text());names=d['facts'];facts=list(names)
 def req(mask):return {k for k,v in names.items() if mask&v}
 rules=[]
 for t in d['transitions']:
  required=req(t['required']);forbidden=req(t['forbidden'])
  if mutant=='missing_boot' and t['action']=='install.done':required.discard('boot')
  target='waiting_input' if mutant=='legacy_gui' and t['action']=='install.start' else t['to']
  guard='TRUE' if mutant=='plan_drift' else 'requestHash = "sealed"'
  attempt=f"attempts + {t['attempt']}"
  rules.append('''    \\/ /\\ phase = %s
       /\\ %s
       /\\ %s \\subseteq f
       /\\ f \\cap %s = {}
       /\\ %s >= activations /\\ %s <= activations + 1
       /\\ %s <= 3
       /\\ phase' = %s
       /\\ activations' = %s /\\ attempts' = %s
       /\\ proofs' = proofs \\cup %s
       /\\ lastFacts' = f /\\ lastHash' = requestHash /\\ lastAction' = %s
'''%(json.dumps(t['from']),guard,tla_set(required),tla_set(forbidden),t['activations'],t['activations'],attempt,json.dumps(target),t['activations'],attempt,tla_set(required),json.dumps(t['action'])))
 text=r'''--------------------------- MODULE Workflow ---------------------------
EXTENDS Naturals, FiniteSets
VARIABLES phase, activations, attempts, proofs, lastFacts, lastHash, lastAction
vars == <<phase, activations, attempts, proofs, lastFacts, lastHash, lastAction>>
Facts == FACTS_PLACEHOLDER
Phases == {"configured","preparing","prepared","installing","installed","drivers","complete","failed"}
Init == /\ phase = "configured" /\ activations = 0 /\ attempts = 0
        /\ proofs = {} /\ lastFacts = {} /\ lastHash = "sealed" /\ lastAction = "init"
Step(f,requestHash) ==
RULES_PLACEHOLDER
SuccessNext == \E f \in SUBSET Facts, requestHash \in {"sealed","changed"}: Step(f,requestHash)
Fail == /\ phase \notin {"complete","failed"}
        /\ phase' = "failed" /\ lastAction' = "fail"
        /\ UNCHANGED <<activations,attempts,proofs,lastFacts,lastHash>>
Next == SuccessNext \/ Fail
Spec == Init /\ [][Next]_vars /\ WF_vars(Next)
SuccessSpec == Init /\ [][SuccessNext]_vars /\ WF_vars(SuccessNext)
TypeOK == phase \in Phases /\ activations \in 0..3 /\ attempts \in 0..3 /\ proofs \subseteq Facts
PlanBound == lastHash = "sealed"
Ordering == /\ (phase \in {"installing","installed","drivers","complete"} => "media" \in proofs)
            /\ (phase \in {"installed","drivers","complete"} => {"image","boot","handoff"} \subseteq proofs)
ActivationOrder == /\ (phase = "configured" => activations=0)
                   /\ (phase \in {"preparing","prepared"} => activations=1)
                   /\ (phase \in {"installing","installed"} => activations=2)
                   /\ (phase \in {"drivers","complete"} => activations=3)
CompletionTruth == phase="complete" => {"plan","bound","handoff","healthy"} \subseteq lastFacts /\ "pending" \notin lastFacts
TargetBound == lastAction \in {"prepare.start","install.start","drivers.start","drivers.resume"} => "bound" \in lastFacts
Terminal == phase \in {"complete","failed"}
Termination == <>Terminal
Completion == <>(phase="complete")
=============================================================================
'''.replace('FACTS_PLACEHOLDER',tla_set(facts)).replace('RULES_PLACEHOLDER',''.join(rules).replace('    \\/','    ',1))
 (directory/'Workflow.tla').write_text(text)
 cfg='''SPECIFICATION Spec
CHECK_DEADLOCK FALSE
INVARIANTS TypeOK PlanBound Ordering ActivationOrder CompletionTruth TargetBound
PROPERTY Termination
'''
 (directory/'Safety.cfg').write_text(cfg)
 (directory/'Success.cfg').write_text(cfg.replace('SPECIFICATION Spec','SPECIFICATION SuccessSpec').replace('PROPERTY Termination','PROPERTY Completion'))

def run(jar,output):
 results=[]
 cases=[('safety','Safety.cfg',None),('conditional_completion','Success.cfg',None),('negative_legacy_gui','Safety.cfg','legacy_gui'),('negative_missing_boot','Safety.cfg','missing_boot'),('negative_plan_drift','Safety.cfg','plan_drift')]
 with tempfile.TemporaryDirectory(prefix='opendeploy-tlc-') as tmp:
  for name,cfg,mutant in cases:
   directory=pathlib.Path(tmp)/name;directory.mkdir();generate(directory,mutant)
   start=time.time();p=subprocess.run(['java','-Xmx1g','-cp',str(jar),'tlc2.TLC','-workers','1','-dump','states.txt','-config',cfg,'Workflow.tla'],cwd=directory,text=True,capture_output=True,timeout=180)
   log=p.stdout+p.stderr
   negative=mutant is not None
   success=('Model checking completed. No error has been found.' in log) if not negative else ('Invariant ' in log and 'is violated' in log and 'Error: The behavior up to this point is:' in log)
   result={'name':name,'expected':'counterexample' if negative else 'pass','matched':success,'exit_code':p.returncode,'seconds':round(time.time()-start,3)}
   for pattern,key in [(r'([\d,]+) states generated','states_generated'),(r'([\d,]+) distinct states found','distinct_states')]:
    matches=re.findall(pattern,log)
    if matches:result[key]=int(matches[-1].replace(',',''))
   (output/(name+'.log')).write_text(log)
   if negative:(output/(name+'.tla')).write_text((directory/'Workflow.tla').read_text())
   if name=='safety':
    dump_path=next(directory.glob('states.txt*'))
    dumped=dump_path.read_text()
    (output/'tlc-states.txt').write_text(dumped.rstrip()+'\n')
    states=set()
    for block in re.split('State [0-9]+:',dumped)[1:]:
     fields={}
     for assignment in block.split('/'+chr(92)):
      if '=' in assignment:
       key,value=assignment.split('=',1)
       if key.strip() in {'phase','activations','attempts','proofs'}:fields[key.strip()]=value.strip()
     if len(fields)!=4:raise SystemExit('Cannot parse TLC state projection: '+block[:500])
     mask=sum(names_mask for fact,names_mask in json.loads(DEFINITION.read_text())['facts'].items() if '"'+fact+'"' in fields['proofs'])
     states.add((json.loads(fields['phase']),int(fields['activations']),int(fields['attempts']),mask))
    projected=[dict(zip(['phase','activations','attempts','proofs'],s)) for s in sorted(states)]
    (output/'tlc-projection.json').write_text(json.dumps(projected,indent=2)+'\n')
    result['projected_control_states']=len(states)
   results.append(result);print(json.dumps(result),flush=True)
   if not success:raise SystemExit(log[-8000:])
 manifest={'tool':'TLC 1.7.4','tool_sha256':hashlib.sha256(jar.read_bytes()).hexdigest(),'workflow_sha256':hashlib.sha256(DEFINITION.read_bytes()).hexdigest(),'results':results,'scope':'finite-state orchestration under explicit external-operation contracts; not proof of Windows/firmware/driver implementation'}
 (output/'results.json').write_text(json.dumps(manifest,indent=2)+'\n')
 generate(output)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--jar',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);run(a.jar.resolve(),a.output.resolve())
