#!/bin/sh
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH
BB=/usr/bin/busybox
mkdir -p /proc /sys /dev /tmp /od-log
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
for m in xhci_pci usb_storage uas sd_mod vfat; do modprobe "$m"; done
od_ready=0
od_wait=0
while [ "$od_wait" -lt 40 ]; do
    /sbin/mdev -s
    for od_dev in /dev/sd*[0-9]; do
        [ -b "$od_dev" ] || continue
        od_meta=$("$BB" blkid "$od_dev" 2>/dev/null)
        case "$od_meta" in
            *'LABEL="OD_PXVIRT"'*)
                if mount -t vfat -o rw "$od_dev" /od-log; then od_ready=1; break; fi
                ;;
        esac
    done
    [ "$od_ready" = 1 ] && break
    sleep 1
    od_wait=$((od_wait+1))
done
if [ "$od_ready" != 1 ]; then
    echo 'OpenDeploy: persistent log USB unavailable. Installation NOT started.'
    while :; do sleep 3600; done
fi
OD_RUN="/od-log/OpenDeploy-install-$(date +%Y%m%d-%H%M%S)"
export OD_RUN
mkdir -p "$OD_RUN"
echo "$OD_RUN" > /tmp/opendeploy-log-path
mkfifo /tmp/opendeploy-boot-output
"$BB" tee -a "$OD_RUN/boot.console.log" </tmp/opendeploy-boot-output >/dev/console &
OD_BOOT_TEE=$!
export OD_BOOT_TEE
exec >/tmp/opendeploy-boot-output 2>&1
echo "OpenDeploy ACTUAL AUTOMATIC INSTALLATION. Persistent logs: $OD_RUN"
dmesg > "$OD_RUN/kernel.initial.log"
cat /dev/kmsg >> "$OD_RUN/kernel.stream.log" 2>&1 &
OD_KERNEL_LOGGER=$!
export OD_KERNEL_LOGGER
od_stop() {
    echo "OpenDeploy startup error: $*"
    dmesg > "$OD_RUN/kernel.failure.log"
    sync
    echo 'Stopped after error. No automatic restart requested by this wrapper.'
    while :; do sleep 3600; done
}
echo 'OpenDeploy: assembling complete ISO in RAM.'
grep -E 'MemTotal|MemAvailable|MemFree' /proc/meminfo
"$BB" cat /od-iso-000 /od-iso-001 /od-iso-002 > /pxvirt.iso || od_stop 'ISO assembly failed'
actual=$("$BB" wc -c < /pxvirt.iso)
[ "$actual" = '2318270464' ] || od_stop 'ISO length mismatch'
"$BB" rm -f /od-iso-000 /od-iso-001 /od-iso-002
grep -E 'MemTotal|MemAvailable|MemFree' /proc/meminfo
echo 'OpenDeploy: ISO ready; entering original installer startup with tracing.'
sync
exec /bin/sh -x /opendeploy-original-init
od_stop 'Original init could not execute'
