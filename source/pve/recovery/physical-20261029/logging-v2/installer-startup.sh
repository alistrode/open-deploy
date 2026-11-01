#!/bin/bash

# OpenDeploy logging: this script remains PID 1; stdin remains the real tty.
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH
if [ -z "$OD_RUN" ] || [ ! -d "$OD_RUN" ]; then
    echo 'OpenDeploy: log directory unavailable; installation stopped.'
    while :; do /bin/sleep 3600; done
fi
exec 9>>"$OD_RUN/installer.trace.log"
export BASH_XTRACEFD=9
PS4='+ ${BASH_SOURCE}:${LINENO}: '
exec > >(tee -a "$OD_RUN/installer.console.log" >/dev/tty1) 2>&1
od_fail() {
    local od_rc="$1" od_line="$2" od_command="$3"
    trap - ERR
    set +x
    printf 'INSTALLATION STOPPED: rc=%s line=%s command=%s\n' "$od_rc" "$od_line" "$od_command" | tee -a "$OD_RUN/failure.log"
    echo 'Installation stopped after an error. No automatic retry or reboot.'
    dmesg > "$OD_RUN/kernel.failure.log" 2>&1 || true
    sync
    while :; do sleep 3600; done
}
printf 'Entered actual installer startup: pid=%s\n' "$$" >> "$OD_RUN/stages.log"
if [ "$$" -ne 1 ]; then od_fail 125 "$LINENO" 'installer must be PID 1'; fi
set -x

trap 'od_fail "$?" "$LINENO" "$BASH_COMMAND"' ERR

# NOTE: we nowadays get exec'd by the initrd's PID 1, so we're the new PID 1

parse_cmdline() {
    start_auto_installer=0
    proxdebug=0
    proxtui=0
    serial=0
    # shellcheck disable=SC2013 # per word splitting is wanted here
    for par in $(cat /proc/cmdline); do
        case $par in
            proxdebug|proxmox-debug)
                proxdebug=1
            ;;
            proxtui|proxmox-tui-mode)
                proxtui=1
            ;;
            proxauto|proxmox-start-auto-installer)
                start_auto_installer=1
            ;;
            console=ttyS*)
                serial=1
            ;;
        esac
    done;
}

debugsh() {
    /bin/bash
}

eject_and_reboot() {
    iso_dev=$(awk '/ iso9660 / {print $1}' /proc/mounts)

    for try in 5 4 3 2 1; do
        echo "unmounting ISO"
        if umount -v -a --types iso9660; then
            break
        fi
        if test -n $try; then
            echo "unmount failed - trying again in 5 seconds"
            sleep 5
        fi
    done

    if [ -n "$iso_dev" ]; then
        eject "$iso_dev" || true # cannot really work currently, don't care
    fi

    umount -l -n /dev

    echo "rebooting - please remove the ISO boot media"
    sleep 3
    reboot -nf
    sleep 5
    echo "trigger reset system request"
    # we do not expect the reboot above to fail, so rather to avoid kpanic when pid 1 exits
    echo b > /proc/sysrq-trigger
    sleep 100
}

real_reboot() {
    trap - ERR

    if [[ -x /etc/init.d/networking ]]; then
        /etc/init.d/networking stop
    fi

    # stop udev (release file handles)
    /etc/init.d/udev stop

    swap=$(awk '/^\/dev\// { print $1 }' /proc/swaps);
    if [ -n "$swap" ]; then
        echo -n "Deactivating swap..."
        swapoff "$swap"
        echo "done."
    fi

    # just to be sure
    sync

    umount -l -n /target >/dev/null 2>&1
    umount -l -n /dev/pts
    umount -l -n /dev/shm
    umount -l -n /run
    [ -d /sys/firmware/efi/efivars ] && umount -l -n /sys/firmware/efi/efivars

    # do not unmount proc and sys for now, at least /proc is still required to trigger the actual
    # reboot, and both are virtual FS only anyway

    echo "Terminate all remaining processes"
    kill -s TERM -1 # TERMinate all but current init (our self) PID 1
    sleep 2
    echo "Kill any remaining processes"
    kill -s KILL -1 # KILL all but current init (our self) PID 1
    sleep 0.5

    eject_and_reboot

    exit 0 # shouldn't be reached, kernel will panic in that case
}

# reachable through the ERR trap
# shellcheck disable=SC2317
err_reboot() {
    printf "\nInstallation aborted - unable to continue (type exit or CTRL-D to reboot)\n"
    debugsh || true
    real_reboot
}

# NOTE: dbus must be launched before this, else iwd cannot work
# FIXME: very crude, still needs to actually copy over any iwd config to target
handle_wireless() {
    wireless_found=
    for iface in /sys/class/net/*; do
        if [ -d "$iface/wireless" ]; then
            wireless_found=1
        fi
    done
    if [ -z $wireless_found ]; then
        return;
    fi

    if [ -x /usr/libexec/iwd ]; then
        echo "wireless device(s) found, starting iwd; use 'iwctl' to manage connections (experimental)"
        /usr/libexec/iwd &
    else
        echo "wireless device found but iwd not available, ignoring"
    fi
}

PATH=/sbin:/bin:/usr/sbin:/usr/bin:/usr/X11R6/bin

echo "Starting Proxmox installation"

# ensure udev doesn't ignores our request; FIXME: not required anymore, as we use switch_root now
export SYSTEMD_IGNORE_CHROOT=1

mount -n -t proc proc /proc
mount -n -t sysfs sysfs /sys
if [ -d /sys/firmware/efi ]; then
    echo "EFI boot mode detected, mounting efivars filesystem"
    mount -n -t efivarfs efivarfs /sys/firmware/efi/efivars
fi
mount -n -t tmpfs tmpfs /run
mkdir -p /run/proxmox-installer

parse_cmdline

# always load most common input drivers
modprobe -q psmouse || true
modprobe -q sermouse ||  true
modprobe -q usbhid ||  true

# load device mapper - used by lilo
modprobe -q dm_mod || true

echo "Installing additional hardware drivers"
export RUNLEVEL=S
export PREVLEVEL=N
/etc/init.d/udev start

mkdir -p /dev/shm
mount -t tmpfs tmpfs /dev/shm

# allow pseudo terminals for debugging in X
mkdir -p /dev/pts
mount -vt devpts devpts /dev/pts -o gid=5,mode=620

# shellcheck disable=SC2207
console_dim=($(IFS=' ' stty size)) # [height, width]
DPI=96
if (("${console_dim[0]}" > 100)) && (("${console_dim[1]}" > 400)); then
    # heuristic only, high resolution can still mean normal/low DPI if it's a really big screen
    # FIXME: use `edid-decode` as it can contain physical dimensions to calculate actual dpi?
    echo "detected huge console, setting bigger font/dpi"
    DPI=192
    export GDK_SCALE=2
    setfont /usr/share/consolefonts/Uni2-Terminus32x16.psf.gz
fi

# set the hostname
hostname pxvirt

if command -v dbus-daemon; then
    echo "starting D-Bus daemon"
    mkdir /run/dbus
    dbus-daemon --system --syslog-only

    if [ $proxdebug -ne 0 ]; then # FIXME: better integration, e.g., use iwgtk?
        handle_wireless # no-op if not wireless dev is found
    fi
fi

# we use a trimmed down debootstrap so make busybox tools available to compensate that
busybox --install -s || true

# Snapshot volatile logs while the real installer runs.
(
    trap - ERR
    set +x
    while :; do
        dmesg > "$OD_RUN/kernel.latest.log" 2>&1
        mkdir -p "$OD_RUN/installer-files"
        for f in /tmp/*.log /var/log/*.log /var/log/installer/* /run/proxmox-installer/*; do
            [ -f "$f" ] || continue
            od_name="${f//\//_}"
            cp "$f" "$OD_RUN/installer-files/$od_name" 2>/dev/null
        done
        sync
        sleep 2 || break
    done
) &

setupcon || echo "setupcon failed, TUI rendering might be garbled - $?"

if [ "$serial" -ne 0 ]; then
    echo "Setting terminal size to 80x24 for serial install"
    stty columns 80 rows 24
fi

if [ $proxdebug -ne 0 ]; then
    /sbin/agetty -o '-p -- \\u' --noclear tty9 &
    printf "\nDropping in debug shell before starting installation\n"
    echo "type 'exit' or press CTRL + D to continue and start the installation wizard"
    debugsh || true
fi

# add custom DHCP options for auto installer
if [ $start_auto_installer -ne 0 ]; then
    echo "Preparing DHCP as potential source to get location of automatic-installation answer file"
    cat >> /etc/dhcp/dhclient.conf <<EOF
option proxmox-auto-installer-manifest-url code 250 = text;
option proxmox-auto-installer-cert-fingerprint code 251 = text;
also request proxmox-auto-installer-manifest-url, proxmox-auto-installer-cert-fingerprint;
EOF
fi

# try to get ip config with dhcp
echo -n "Attempting to get DHCP leases... "
dhclient -v
echo "done"

echo "Starting chrony for opportunistic time-sync... "
chronyd || echo "starting chrony failed ($?)"

echo "Starting a root shell on tty3."
setsid /sbin/agetty -a root --noclear tty3 &

/usr/bin/proxmox-low-level-installer dump-env

if [ $proxtui -ne 0 ]; then
    echo "Starting the TUI installer"
    /usr/bin/proxmox-tui-installer 2>/dev/tty2
elif [ $start_auto_installer -ne 0 ]; then
    echo "Caching device info from udev"
    /usr/bin/proxmox-low-level-installer dump-udev

    if [ -f /cdrom/auto-installer-mode.toml ]; then
        echo "Fetching answers for automatic installation"
        /usr/bin/proxmox-fetch-answer >/run/automatic-installer-answers
    else
        printf "\nAutomatic installation selected but no config for fetching the answer file found!\n"
        echo "Starting debug shell, to fetch the answer file manually use:"
        echo "  proxmox-fetch-answer MODE >/run/automatic-installer-answers"
        echo "and enter 'exit' or press 'CTRL' + 'D' when finished."
        debugsh || true
    fi
    echo "Starting automatic installation"

    if /usr/bin/proxmox-auto-installer </run/automatic-installer-answers; then
        echo 'automatic installer returned rc=0' >> "$OD_RUN/stages.log"
        if /usr/bin/proxmox-post-hook </run/automatic-installer-answers; then
            echo 'post-install hook returned rc=0' >> "$OD_RUN/stages.log"
        else
            od_fail "$?" "$LINENO" 'proxmox-post-hook'
        fi
    else
        od_fail "$?" "$LINENO" 'proxmox-auto-installer'
    fi

else
    echo "Starting the installer GUI - see tty2 (CTRL+ALT+F2) for any errors..."
    xinit -- -dpi "$DPI" -s 0 >/dev/tty2 2>&1
fi

# just to be sure everything is on disk
sync

if [ $proxdebug -ne 0 ]; then 
    printf "\nDebug shell after installation exited (type exit or CTRL-D to reboot)\n"
    debugsh || true
fi

echo "Installation done, rebooting... "
echo "installer completed; normal reboot requested" >> "$OD_RUN/stages.log"
sync

killall5 -15

real_reboot

# never reached
# shellcheck disable=SC2317
exit 0
