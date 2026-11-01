--------------------------- MODULE Workflow ---------------------------
EXTENDS Naturals, FiniteSets
VARIABLES phase, activations, attempts, proofs, lastFacts, lastHash, lastAction
vars == <<phase, activations, attempts, proofs, lastFacts, lastHash, lastAction>>
Facts == {"plan", "bound", "inputs", "media", "image", "boot", "handoff", "healthy", "pending"}
Phases == {"configured","preparing","prepared","installing","installed","drivers","complete","failed"}
Init == /\ phase = "configured" /\ activations = 0 /\ attempts = 0
        /\ proofs = {} /\ lastFacts = {} /\ lastHash = "sealed" /\ lastAction = "init"
Step(f,requestHash) ==
     /\ phase = "configured"
       /\ requestHash = "sealed"
       /\ {"bound", "inputs", "plan"} \subseteq f
       /\ f \cap {} = {}
       /\ 1 >= activations /\ 1 <= activations + 1
       /\ attempts + 0 <= 3
       /\ phase' = "preparing"
       /\ activations' = 1 /\ attempts' = attempts + 0
       /\ proofs' = proofs \cup {"bound", "inputs", "plan"}
       /\ lastFacts' = f /\ lastHash' = requestHash /\ lastAction' = "prepare.start"
    \/ /\ phase = "preparing"
       /\ requestHash = "sealed"
       /\ {"media", "plan"} \subseteq f
       /\ f \cap {} = {}
       /\ 1 >= activations /\ 1 <= activations + 1
       /\ attempts + 0 <= 3
       /\ phase' = "prepared"
       /\ activations' = 1 /\ attempts' = attempts + 0
       /\ proofs' = proofs \cup {"media", "plan"}
       /\ lastFacts' = f /\ lastHash' = requestHash /\ lastAction' = "prepare.done"
    \/ /\ phase = "prepared"
       /\ requestHash = "sealed"
       /\ {"bound", "media", "plan"} \subseteq f
       /\ f \cap {} = {}
       /\ 2 >= activations /\ 2 <= activations + 1
       /\ attempts + 0 <= 3
       /\ phase' = "installing"
       /\ activations' = 2 /\ attempts' = attempts + 0
       /\ proofs' = proofs \cup {"bound", "media", "plan"}
       /\ lastFacts' = f /\ lastHash' = requestHash /\ lastAction' = "install.start"
    \/ /\ phase = "installing"
       /\ requestHash = "sealed"
       /\ {"handoff", "image", "plan"} \subseteq f
       /\ f \cap {} = {}
       /\ 2 >= activations /\ 2 <= activations + 1
       /\ attempts + 0 <= 3
       /\ phase' = "installed"
       /\ activations' = 2 /\ attempts' = attempts + 0
       /\ proofs' = proofs \cup {"handoff", "image", "plan"}
       /\ lastFacts' = f /\ lastHash' = requestHash /\ lastAction' = "install.done"
    \/ /\ phase = "installed"
       /\ requestHash = "sealed"
       /\ {"bound", "handoff", "plan"} \subseteq f
       /\ f \cap {} = {}
       /\ 3 >= activations /\ 3 <= activations + 1
       /\ attempts + 1 <= 3
       /\ phase' = "drivers"
       /\ activations' = 3 /\ attempts' = attempts + 1
       /\ proofs' = proofs \cup {"bound", "handoff", "plan"}
       /\ lastFacts' = f /\ lastHash' = requestHash /\ lastAction' = "drivers.start"
    \/ /\ phase = "drivers"
       /\ requestHash = "sealed"
       /\ {"bound", "handoff", "plan"} \subseteq f
       /\ f \cap {} = {}
       /\ 3 >= activations /\ 3 <= activations + 1
       /\ attempts + 1 <= 3
       /\ phase' = "drivers"
       /\ activations' = 3 /\ attempts' = attempts + 1
       /\ proofs' = proofs \cup {"bound", "handoff", "plan"}
       /\ lastFacts' = f /\ lastHash' = requestHash /\ lastAction' = "drivers.resume"
    \/ /\ phase = "drivers"
       /\ requestHash = "sealed"
       /\ {"bound", "handoff", "healthy", "plan"} \subseteq f
       /\ f \cap {"pending"} = {}
       /\ 3 >= activations /\ 3 <= activations + 1
       /\ attempts + 0 <= 3
       /\ phase' = "complete"
       /\ activations' = 3 /\ attempts' = attempts + 0
       /\ proofs' = proofs \cup {"bound", "handoff", "healthy", "plan"}
       /\ lastFacts' = f /\ lastHash' = requestHash /\ lastAction' = "drivers.done"

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
