#!/bin/bash
#
# Biesse Skill 1224 - limit-homing monitor for X1, X2, Y and Z, read-only.
# Logs homing state whenever something changes; survives LinuxCNC restarts.
#
# Usage:  ./home-watch.sh [seconds]     (default 900)
#

SECS=${1:-900}
end=$((SECONDS + SECS))
# name joint comparator drive
AXES=("X1 0 x1-home-cmp 00" "X2 1 x2-home-cmp 01" "Y 2 y-home-cmp 02" "Z 3 z-home-cmp 03")

while [ $SECONDS -lt $end ]; do
    until pgrep -x rtapi_app >/dev/null && halcmd getp x1-home-cmp.out >/dev/null 2>&1; do
        [ $SECONDS -ge $end ] && { echo "$(date +%T) monitor stopped"; exit 0; }
        sleep 1
    done
    echo "$(date +%T) LinuxCNC up, watching X1, X2, Y and Z"

    declare -A prev=()
    while [ $SECONDS -lt $end ] && pgrep -x rtapi_app >/dev/null; do
        any_homing=0
        for a in "${AXES[@]}"; do
            set -- $a
            name=$1; j=$2; cmp=$3; drv=$4
            homing=$(halcmd getp joint.$j.homing 2>/dev/null) || break 2
            state="homing=$homing homed=$(halcmd getp joint.$j.homed) home-sw=$(halcmd getp $cmp.out) enable=$(halcmd getp joint.$j.amp-enable-out) index=$(halcmd getp joint.$j.index-enable)"
            vals="pos=$(halcmd getp joint.$j.pos-fb) ferr=$(halcmd getp joint.$j.f-error) counts=$(halcmd getp nyx.0.servo-$drv.counts)"
            if [ "$state" != "${prev[$name]}" ]; then
                echo "$(date +%T.%N | cut -c1-12) $name $state  $vals"
                prev[$name]=$state
            elif [ "$homing" = "TRUE" ]; then
                echo "$(date +%T.%N | cut -c1-12) $name   $vals"
                any_homing=1
            fi
        done
        [ $any_homing = 1 ] && sleep 0.2
        sleep 0.05
    done
    echo "$(date +%T) LinuxCNC stopped"
done
echo "$(date +%T) monitor stopped"
