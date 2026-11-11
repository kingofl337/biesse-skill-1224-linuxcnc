#!/bin/bash
#
# Biesse Skill 1224 - Z homing monitor (read-only).
# Logs Z homing state whenever something changes; keeps running across
# LinuxCNC restarts until the time is up.
#
# Usage:  ./zhome-watch.sh [seconds]     (default 900)
#

SECS=${1:-900}
end=$((SECONDS + SECS))

while [ $SECONDS -lt $end ]; do
    until pgrep -x rtapi_app >/dev/null && halcmd getp z-home-cmp.out >/dev/null 2>&1; do
        [ $SECONDS -ge $end ] && { echo "$(date +%T) monitor stopped"; exit 0; }
        sleep 1
    done
    echo "$(date +%T) LinuxCNC up, watching Z"

    prev=""
    while [ $SECONDS -lt $end ] && pgrep -x rtapi_app >/dev/null; do
        homing=$(halcmd getp joint.3.homing 2>/dev/null) || break
        homed=$(halcmd getp joint.3.homed)
        sw=$(halcmd getp z-home-cmp.out)
        en=$(halcmd getp joint.3.amp-enable-out)
        idx=$(halcmd getp joint.3.index-enable)
        state="homing=$homing homed=$homed home-sw=$sw enable=$en index=$idx"
        pos=$(halcmd getp joint.3.pos-fb)
        ferr=$(halcmd getp joint.3.f-error)
        counts=$(halcmd getp nyx.0.servo-03.counts)
        if [ "$state" != "$prev" ]; then
            echo "$(date +%T.%N | cut -c1-12) $state  pos=$pos ferr=$ferr counts=$counts"
            prev=$state
        elif [ "$homing" = "TRUE" ]; then
            echo "$(date +%T.%N | cut -c1-12)   pos=$pos ferr=$ferr counts=$counts"
            sleep 0.2
        fi
        sleep 0.05
    done
    echo "$(date +%T) LinuxCNC stopped"
done
echo "$(date +%T) monitor stopped"
