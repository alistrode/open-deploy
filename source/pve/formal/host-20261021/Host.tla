----------------------- MODULE Host -----------------------
EXTENDS Naturals
CONSTANTS UnitIncluded, PasswordMatches, MediaProbeCorrect, InitialCertFailures
VARIABLES phase, failures, pending
vars == <<phase, failures, pending>>
Init == /\ phase = "configured"
        /\ failures = InitialCertFailures /\ pending = TRUE
Move(a,b) == /\ phase = a /\ phase' = b
             /\ UNCHANGED <<failures,pending>>
Next == \/ Move("configured", "media")
        \/ Move("media", "packages")
        \/ /\ phase = "packages"
           /\ phase' = IF UnitIncluded THEN "bootable" ELSE "install_failed"
           /\ UNCHANGED <<failures,pending>>
        \/ Move("bootable", "host_booted")
        \/ /\ phase = "host_booted"
           /\ phase' = IF MediaProbeCorrect THEN "payload_copied" ELSE "media_missing"
           /\ UNCHANGED <<failures,pending>>
        \/ /\ phase = "payload_copied" /\ failures > 0
           /\ failures' = failures - 1
           /\ UNCHANGED <<phase,pending>>
        \/ /\ phase = "payload_copied" /\ failures = 0
           /\ phase' = "tls_ready" /\ UNCHANGED <<failures,pending>>
        \/ /\ phase = "tls_ready"
           /\ phase' = IF PasswordMatches THEN "authenticated" ELSE "api_rejected"
           /\ UNCHANGED <<failures,pending>>
        \/ /\ phase = "authenticated" /\ phase' = "registered"
           /\ pending' = FALSE /\ UNCHANGED failures
Spec == Init /\ [][Next]_vars /\ WF_vars(Next)
TypeOK == /\ phase \in {"configured","media","packages","bootable",
                        "host_booted","payload_copied","tls_ready","authenticated","registered",
                        "install_failed","api_rejected","media_missing"}
          /\ failures \in 0..InitialCertFailures /\ pending \in BOOLEAN
NoFalseReady == phase = "registered" => (UnitIncluded /\ PasswordMatches /\ MediaProbeCorrect /\ ~pending)
NoEarlyPendingRemoval == phase # "registered" => pending
Completion == <>(phase = "registered")
===========================================================
