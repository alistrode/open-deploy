------------------- MODULE Deploy -------------------
EXTENDS Naturals, FiniteSets
CONSTANT successOnly
VARIABLES phase, lastFacts, lastHash, lastAction
vars == <<phase,lastFacts,lastHash,lastAction>>
Facts == {"boot_preserved","guest_bound","guest_healthy","host_bound","inputs_verified","relay_running","snapshot_verified","vm_configured","vm_owned","vmid_free"}
Init == /\ phase = "configured" /\ lastFacts = {} /\ lastHash = "sealed" /\ lastAction = "init"
Step(f,h) ==
 \/ /\ phase = "configured"
    /\ {"boot_preserved","inputs_verified"} \subseteq f
    /\ h = "sealed"
    /\ (~successOnly \/ TRUE)
    /\ phase' = "media_ready" /\ lastFacts' = f /\ lastHash' = h /\ lastAction' = "media.done"
 \/ /\ phase = "media_ready"
    /\ {"host_bound","relay_running"} \subseteq f
    /\ h = "sealed"
    /\ (~successOnly \/ TRUE)
    /\ phase' = "host_ready" /\ lastFacts' = f /\ lastHash' = h /\ lastAction' = "host.done"
 \/ /\ phase = "host_ready"
    /\ {"host_bound","inputs_verified","vmid_free"} \subseteq f
    /\ h = "sealed"
    /\ (~successOnly \/ TRUE)
    /\ phase' = "vm_creating" /\ lastFacts' = f /\ lastHash' = h /\ lastAction' = "vm.intent"
 \/ /\ phase = "vm_creating"
    /\ {"host_bound","vm_configured","vm_owned"} \subseteq f
    /\ h = "sealed"
    /\ (~successOnly \/ TRUE)
    /\ phase' = "installing" /\ lastFacts' = f /\ lastHash' = h /\ lastAction' = "vm.done"
 \/ /\ phase = "installing"
    /\ {"guest_bound","guest_healthy","vm_owned"} \subseteq f
    /\ h = "sealed"
    /\ (~successOnly \/ TRUE)
    /\ phase' = "guest_ready" /\ lastFacts' = f /\ lastHash' = h /\ lastAction' = "guest.done"
 \/ /\ phase = "guest_ready"
    /\ {"guest_bound","guest_healthy","vm_owned"} \subseteq f
    /\ h = "sealed"
    /\ (~successOnly \/ TRUE)
    /\ phase' = "snapshotting" /\ lastFacts' = f /\ lastHash' = h /\ lastAction' = "snapshot.intent"
 \/ /\ phase = "snapshotting"
    /\ {"guest_bound","guest_healthy","snapshot_verified","vm_owned"} \subseteq f
    /\ h = "sealed"
    /\ (~successOnly \/ TRUE)
    /\ phase' = "complete" /\ lastFacts' = f /\ lastHash' = h /\ lastAction' = "snapshot.done"
 \/ /\ phase = "complete"
    /\ {"snapshot_verified","vm_owned"} \subseteq f
    /\ h = "sealed"
    /\ (~successOnly \/ FALSE)
    /\ phase' = "recovering" /\ lastFacts' = f /\ lastHash' = h /\ lastAction' = "recover.intent"
 \/ /\ phase = "recovering"
    /\ {"guest_bound","guest_healthy","vm_owned"} \subseteq f
    /\ h = "sealed"
    /\ (~successOnly \/ FALSE)
    /\ phase' = "guest_ready" /\ lastFacts' = f /\ lastHash' = h /\ lastAction' = "recover.done"

Next == \E f \in SUBSET Facts, h \in {"sealed","changed"}: Step(f,h)
Spec == Init /\ [][Next]_vars /\ WF_vars(Next)
TypeOK == phase \in {"complete","configured","guest_ready","host_ready","installing","media_ready","recovering","snapshotting","vm_creating"} /\ lastFacts \subseteq Facts
PlanBound == lastHash = "sealed"
Ownership == lastAction \in {"vm.done","guest.done","snapshot.intent","snapshot.done","recover.intent","recover.done"} => "vm_owned" \in lastFacts
CompletionTruth == phase="complete" => {"snapshot_verified","guest_healthy","guest_bound","vm_owned"} \subseteq lastFacts
CreationBound == lastAction="vm.intent" => {"vmid_free","host_bound","inputs_verified"} \subseteq lastFacts
Completion == <>(phase="complete")
=====================================================
