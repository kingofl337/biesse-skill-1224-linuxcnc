#!/bin/bash
#
# Biesse Skill 1224 - live switch test (read-only, needs LinuxCNC running)
# Prints every change of the drive inputs (nyx servo-MM.in-00..02), drive
# alarm/warning, joint limit/home flags and the joint position at that moment.
#
# Usage:  ./io-watch.sh [seconds]      (default 120, Ctrl-C to stop early)
# Then actuate one switch at a time (press by hand or jog slowly onto it).
#

SECS=${1:-120}
NAMES=(X1 X2 Y Z)

snapshot() {
    for s in 0 1 2 3; do
        for p in in-00 in-01 in-02 alarm warning; do
            echo "${NAMES[$s]}.$p=$(halcmd getp nyx.0.servo-0$s.$p)"
        done
    done
}

pos() {
    echo "X1=$(halcmd getp joint.0.pos-fb) X2=$(halcmd getp joint.1.pos-fb) Y=$(halcmd getp joint.2.pos-fb) Z=$(halcmd getp joint.3.pos-fb)"
}

pgrep -x rtapi_app >/dev/null || { echo "LinuxCNC is not running"; exit 1; }

echo "Watching drive inputs for $SECS s. Actuate ONE switch at a time."
prev=$(snapshot)
echo "start: $(echo "$prev" | grep TRUE | tr '\n' ' ')"
echo "       $(pos)"
end=$((SECONDS + SECS))
while [ $SECONDS -lt $end ]; do
    cur=$(snapshot)
    if [ "$cur" != "$prev" ]; then
        diff <(echo "$prev") <(echo "$cur") | grep '^>' | sed "s/^> /$(date +%T) /"
        echo "         $(pos)"
        prev=$cur
    fi
    sleep 0.05
done
echo "done"
