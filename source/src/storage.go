package main

// Already expanded drivers are verified before media creation. WinPE injects
// signed storage/network packages before enumerating the target disks.
func extractStorage(root string) error { return verifyBootstrap(root) }
