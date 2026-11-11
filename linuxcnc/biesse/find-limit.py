#!/usr/bin/env python3
#
# Biesse Skill 1224 - find the far overtravel limit of one axis (MOVES THE MACHINE).
#
# Drives slowly toward the far end in machine coordinates until the drive stops on
# its overtravel switch. nyx does not report P-OT/N-OT, so the stop is detected from
# LinuxCNC's following error (> THRESHOLD mm), the motion is aborted before the
# MIN_FERROR fault, the stop position is printed, and the axis backs off.
# The soft limit on that side is widened live for the probe and restored afterwards.
#
# Usage:  python3 find-limit.py AXIS TARGET FEED
#   AXIS    x | y | z
#   TARGET  machine position well beyond the expected limit, e.g. -3300
#   FEED    mm/min (X/Y 900, Z 300)
#
# Requires: LinuxCNC running, machine on, all joints homed, idle.

import sys
import time
import linuxcnc

THRESHOLD = 1.2      # mm following error that means "the drive has stopped"
BACKOFF = 10.0       # mm

JOINTS = {"x": [0, 1], "y": [2], "z": [3]}
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def main():
    axis = sys.argv[1].lower()
    target = float(sys.argv[2])
    feed = float(sys.argv[3])
    joints = JOINTS[axis]

    s = linuxcnc.stat()
    c = linuxcnc.command()
    s.poll()
    if s.estop or s.task_state != linuxcnc.STATE_ON:
        sys.exit("machine is not on")
    if not all(s.homed[j] for j in range(s.joints)):
        sys.exit("not all joints homed")
    if s.interp_state != linuxcnc.INTERP_IDLE:
        sys.exit("interpreter busy")

    start = [s.joint_actual_position[j] for j in joints]
    toward_min = target < start[0]
    side = "min" if toward_min else "max"
    old = {}
    ax = AXIS_INDEX[axis]
    old["axis"] = s.axis[ax]["min_position_limit" if toward_min else "max_position_limit"]
    for j in joints:
        old[j] = s.joint[j]["min_position_limit" if toward_min else "max_position_limit"]

    import subprocess

    def setlim(pin, val):
        subprocess.run(["halcmd", "setp", pin, str(val)], check=True)

    print(f"{axis.upper()} from {start} toward {target} at F{feed}, threshold {THRESHOLD} mm")
    setlim(f"ini.{axis}.{side}_limit", target)
    for j in joints:
        setlim(f"ini.{j}.{side}_limit", target)
    time.sleep(0.3)

    stop_pos = None
    try:
        c.mode(linuxcnc.MODE_MDI)
        c.wait_complete()
        if axis in ("x", "y"):
            # retract Z to machine 0 (top) before any X/Y move
            c.mdi("G53 G1 Z0 F1500")
            c.wait_complete()
            while True:
                s.poll()
                if s.interp_state == linuxcnc.INTERP_IDLE and s.inpos:
                    break
                time.sleep(0.05)
            s.poll()
            if abs(s.joint_actual_position[3]) > 0.05:
                print(f"Z did not reach 0 ({s.joint_actual_position[3]:.3f}), stopping")
                return
            print("Z at machine 0")
        c.mdi(f"G53 G1 {axis.upper()}{target:.3f} F{feed:.0f}")
        t0 = time.time()
        moving = False
        while True:
            s.poll()
            ferr = max(abs(s.joint[j]["ferror_current"]) for j in joints)
            if s.task_state != linuxcnc.STATE_ON:
                print("machine switched off during probe")
                return
            if ferr > THRESHOLD:
                c.abort()
                time.sleep(0.5)
                s.poll()
                stop_pos = [s.joint_actual_position[j] for j in joints]
                peak = max(abs(s.joint[j]["ferror_current"]) for j in joints)
                print(f"LIMIT: drive stopped at {['%.3f' % p for p in stop_pos]} "
                      f"(ferr {ferr:.2f} mm when caught)")
                break
            if s.interp_state == linuxcnc.INTERP_IDLE and time.time() - t0 > 1.0:
                s.poll()
                print(f"reached target {target} without hitting a limit "
                      f"(now {[s.joint_actual_position[j] for j in joints]})")
                break
            time.sleep(0.005)
    finally:
        s.poll()
        if s.task_state == linuxcnc.STATE_ON and stop_pos is not None:
            back = stop_pos[0] + (BACKOFF if toward_min else -BACKOFF)
            c.mode(linuxcnc.MODE_MDI)
            c.wait_complete()
            c.mdi(f"G53 G1 {axis.upper()}{back:.3f} F{feed:.0f}")
            c.wait_complete()
            while True:
                s.poll()
                if s.interp_state == linuxcnc.INTERP_IDLE and s.inpos:
                    break
                time.sleep(0.05)
            print(f"backed off to {back:.3f}")
        setlim(f"ini.{axis}.{side}_limit", old["axis"])
        for j in joints:
            setlim(f"ini.{j}.{side}_limit", old[j])
        print(f"{side} soft limit restored to {old['axis']}")


if __name__ == "__main__":
    main()
