#!/usr/bin/env python3
# Record changes of the nyx servo input/monitor pins (read-only) for N seconds.
# Usage: nyx_watch.py seconds > log
import sys
import time
import hal

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 120
PINS = ("in-00", "in-01", "in-02", "mon1", "mon2", "mon12", "alarm", "warning",
        "torque-clamped", "z-passed", "in-position", "alarm-code")
JOINT = {0: 0, 1: 1, 2: 2, 3: 3}

comp = hal.component("nyx-watch")   # hal.get_value needs a HAL connection
comp.ready()
last = {}
t0 = time.time()
print("t      drive    pin            value        joint-pos")
while time.time() - t0 < SECONDS:
    for s in range(4):
        for p in PINS:
            name = "nyx.0.servo-%02d.%s" % (s, p)
            try:
                v = hal.get_value(name)
            except Exception:
                continue
            if last.get(name) != v:
                pos = hal.get_value("joint.%d.pos-fb" % JOINT[s])
                shown = ("0x%08X" % (v & 0xFFFFFFFF)) if isinstance(v, int) and not isinstance(v, bool) else v
                if name in last:
                    print("%6.2f  servo-%02d %-14s %-12s %10.3f" % (time.time() - t0, s, p, shown, pos))
                else:
                    print("start   servo-%02d %-14s %-12s %10.3f" % (s, p, shown, pos))
                last[name] = v
    sys.stdout.flush()
    time.sleep(0.02)
print("done")
