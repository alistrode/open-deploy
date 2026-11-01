------------------------- MODULE Snapshot -------------------------
EXTENDS Naturals
CONSTANTS AutoFinalize, ManualFinalize, FaultOnce, AllowRerun, Configured
VARIABLES phase, booted, service, guestHealthy, controller, launched,
          faultsLeft, snapshotVerified, rdpReady
vars == <<phase, booted, service, guestHealthy, controller, launched,
          faultsLeft, snapshotVerified, rdpReady>>

Init == /\ phase = IF Configured THEN "configured" ELSE "needs_input"
        /\ booted = FALSE /\ service = "unregistered"
        /\ guestHealthy = FALSE /\ controller = "idle" /\ launched = 0
        /\ faultsLeft = IF FaultOnce THEN 1 ELSE 0
        /\ snapshotVerified = FALSE /\ rdpReady = FALSE

Prepare == /\ phase = "configured" /\ phase' = "media_ready"
           /\ UNCHANGED <<booted, service, guestHealthy, controller, launched,
                           faultsLeft, snapshotVerified, rdpReady>>
BootAndRegister == /\ phase = "media_ready" /\ ~booted
                   /\ booted' = TRUE /\ service' = "registered"
                   /\ UNCHANGED <<phase, guestHealthy, controller, launched,
                                   faultsLeft, snapshotVerified, rdpReady>>
Bootstrap == /\ phase = "media_ready" /\ service = "registered"
             /\ phase' = "host_ready" /\ service' = "bootstrapped"
             /\ UNCHANGED <<booted, guestHealthy, controller, launched,
                             faultsLeft, snapshotVerified, rdpReady>>
VmIntent == /\ phase = "host_ready" /\ service = "bootstrapped"
            /\ phase' = "vm_creating"
            /\ UNCHANGED <<booted, service, guestHealthy, controller, launched,
                            faultsLeft, snapshotVerified, rdpReady>>
Install == /\ phase = "vm_creating" /\ service = "bootstrapped"
           /\ phase' = "installing" /\ service' = "exited"
           /\ UNCHANGED <<booted, guestHealthy, controller, launched,
                           faultsLeft, snapshotVerified, rdpReady>>
GuestFinish == /\ phase = "installing" /\ ~guestHealthy
               /\ guestHealthy' = TRUE
               /\ UNCHANGED <<phase, booted, service, controller, launched,
                               faultsLeft, snapshotVerified, rdpReady>>
LaunchFinalize == /\ phase = "installing" /\ guestHealthy
                  /\ controller = "idle" /\ (AutoFinalize \/ ManualFinalize)
                  /\ controller' = "active" /\ launched' = 1
                  /\ UNCHANGED <<phase, booted, service, guestHealthy,
                                  faultsLeft, snapshotVerified, rdpReady>>
GuestDone == /\ phase = "installing" /\ controller = "active" /\ guestHealthy
             /\ phase' = "guest_ready"
             /\ UNCHANGED <<booted, service, guestHealthy, controller, launched,
                             faultsLeft, snapshotVerified, rdpReady>>
SnapshotIntent == /\ phase = "guest_ready" /\ controller = "active"
                  /\ phase' = "snapshotting"
                  /\ UNCHANGED <<booted, service, guestHealthy, controller,
                                  launched, faultsLeft, snapshotVerified, rdpReady>>
SnapshotFault == /\ phase = "snapshotting" /\ controller = "active"
                 /\ faultsLeft = 1 /\ ~snapshotVerified
                 /\ controller' = "failed" /\ faultsLeft' = 0
                 /\ UNCHANGED <<phase, booted, service, guestHealthy,
                                 launched, snapshotVerified, rdpReady>>
Rerun == /\ AllowRerun /\ controller = "failed" /\ launched = 1
         /\ controller' = "active" /\ launched' = 2
         /\ UNCHANGED <<phase, booted, service, guestHealthy, faultsLeft,
                         snapshotVerified, rdpReady>>
SnapshotSuccess == /\ phase = "snapshotting" /\ controller = "active"
                   /\ faultsLeft = 0 /\ ~snapshotVerified
                   /\ snapshotVerified' = TRUE
                   /\ UNCHANGED <<phase, booted, service, guestHealthy,
                                   controller, launched, faultsLeft, rdpReady>>
VerifyRestartAndRdp == /\ phase = "snapshotting" /\ controller = "active"
                      /\ snapshotVerified /\ ~rdpReady
                      /\ rdpReady' = TRUE
                      /\ UNCHANGED <<phase, booted, service, guestHealthy,
                                      controller, launched, faultsLeft, snapshotVerified>>
Complete == /\ phase = "snapshotting" /\ controller = "active"
            /\ snapshotVerified /\ guestHealthy /\ rdpReady
            /\ phase' = "complete" /\ controller' = "done"
            /\ UNCHANGED <<booted, service, guestHealthy, launched,
                            faultsLeft, snapshotVerified, rdpReady>>
Next == Prepare \/ BootAndRegister \/ Bootstrap \/ VmIntent \/ Install
        \/ GuestFinish \/ LaunchFinalize \/ GuestDone \/ SnapshotIntent
        \/ SnapshotFault \/ Rerun \/ SnapshotSuccess \/ VerifyRestartAndRdp \/ Complete
Spec == Init /\ [][Next]_vars /\ WF_vars(Next)
TypeOK == /\ phase \in {"needs_input", "configured", "media_ready", "host_ready",
                        "vm_creating", "installing", "guest_ready", "snapshotting", "complete"}
          /\ controller \in {"idle", "active", "failed", "done"}
          /\ service \in {"unregistered", "registered", "bootstrapped", "exited"}
          /\ guestHealthy \in BOOLEAN /\ booted \in BOOLEAN
          /\ snapshotVerified \in BOOLEAN /\ rdpReady \in BOOLEAN
          /\ launched \in 0..2 /\ faultsLeft \in 0..1
NoFalseComplete == phase = "complete" => snapshotVerified /\ guestHealthy /\ rdpReady
NoUnscheduledFinalize == controller # "idle" => (AutoFinalize \/ ManualFinalize)
Completion == <>(phase = "complete")
===================================================================
