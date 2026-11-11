#!/usr/bin/env python3
# Log one joint's homing every 20 ms (read-only): positions, home switch, index-enable,
# home state, nyx inputs and counts.  Usage: home_log.py seconds j:s [j:s ...] > log
import sys
import time
import hal

# joints and servos as "j:s" pairs, e.g. home_log.py 300 0:0 1:1
SECONDS = float(sys.argv[1])
PINS = []
for pair in sys.argv[2:]:
    J, S = (int(x) for x in pair.split(":"))
    PINS += ["joint.%d.%s" % (J, p) for p in ("pos-fb", "motor-pos-fb", "motor-offset", "home-state",
                                             "homing", "home-sw-in", "index-enable", "f-error")]
    PINS += ["nyx.0.servo-%02d.%s" % (S, p) for p in ("in-00", "in-01", "in-02", "z-passed",
                                                      "torque-clamped", "counts")]

comp = hal.component("home-log")
comp.ready()
print("t " + " ".join(p.split(".")[1][-2:] + "." + p.split(".")[-1] for p in PINS))
last = None
t0 = time.time()
while time.time() - t0 < SECONDS:
    row = []
    for p in PINS:
        try:
            v = hal.get_value(p)
        except Exception:
            v = None
        row.append(("%.3f" % v) if isinstance(v, float) else str(int(v)) if isinstance(v, bool) else str(v))
    if row != last:
        print("%.2f %s" % (time.time() - t0, " ".join(row)))
        sys.stdout.flush()
        last = row
    time.sleep(0.02)
print("done")
