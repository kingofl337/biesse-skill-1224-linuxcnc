#!/bin/bash
#
# Biesse Skill 1224 - record X/Y following error while a program runs (read-only).
# Waits for LinuxCNC and for a program to start, records at the 1 kHz servo rate
# until it ends, then prints a summary. Raw data: /tmp/ferr-run.txt
#
# Usage:  ./ferr-record.sh [max-seconds]     (default 3600)
#
# columns: X1 ferr, X1 limit, X2 ferr, Y ferr, Y limit, X vel-cmd, Y vel-cmd, enabled

MAX=${1:-3600}
end=$((SECONDS + MAX))
OUT=/tmp/ferr-run.txt

until pgrep -x rtapi_app >/dev/null && [ "$(halcmd getp halui.program.is-running 2>/dev/null)" = "TRUE" ]; do
    [ $SECONDS -ge $end ] && { echo "no program started"; exit 1; }
    sleep 0.5
done
echo "$(date +%T) program running, recording"

if ! halcmd show comp 2>/dev/null | grep -q "sampler"; then
    halcmd loadrt sampler depth=20000 cfg=fffffffb
    halcmd addf sampler.0 servo-thread
    i=0
    for p in joint.0.f-error joint.0.f-error-lim joint.1.f-error joint.2.f-error \
             joint.2.f-error-lim joint.0.vel-cmd joint.2.vel-cmd motion.motion-enabled; do
        halcmd net ferrrec$i $p sampler.0.pin.$i
        i=$((i + 1))
    done
fi

halsampler -c 0 > $OUT 2>/dev/null &
SPID=$!
while [ $SECONDS -lt $end ] && [ "$(halcmd getp halui.program.is-running 2>/dev/null)" = "TRUE" ]; do
    sleep 0.5
done
sleep 1
kill $SPID 2>/dev/null
echo "$(date +%T) program ended, $(wc -l < $OUT) samples"

awk 'function ab(v){return v<0?-v:v}
{ for (c=1;c<=7;c++) { a=ab($c); if (a>m[c]) { m[c]=a; at[c]=NR } }
  r=(ab($2)>0)?ab($1)/ab($2):0; if (r>rx) { rx=r; rxl=NR }
  r=(ab($5)>0)?ab($4)/ab($5):0; if (r>ry) { ry=r; ryl=NR }
  if ($8==0 && en==1) trips++; en=$8 }
END {
  printf "max |ferr|  X1 %.3f  X2 %.3f  Y %.3f mm\n", m[1], m[3], m[4]
  printf "max speed   X %.0f  Y %.0f mm/s\n", m[6], m[7]
  printf "worst ferr/limit  X %.0f%%  Y %.0f%%\n", rx*100, ry*100
  printf "machine dropped out: %d time(s)\n", trips+0 }' $OUT
