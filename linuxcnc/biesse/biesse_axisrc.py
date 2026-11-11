# Biesse Skill 1224 - AXIS user command file ([DISPLAY] USER_COMMAND_FILE)
#
# Park = retract Z to its home position, then rapid X/Y to their home positions.
#  - "Park" button on the AXIS toolbar
#  - closing the window or File > Quit offers to park before LinuxCNC closes
# All axes home on their limit switches (Home All), so no position needs to
# survive a shutdown; a reminder pops up at machine-on while unhomed.
#
# Executed by AXIS with exec(); root_window and linuxcnc come from AXIS.

# Park at each axis's HOME position from the INI (X: JOINT_0, Y: JOINT_2, Z: JOINT_3),
# so parking always matches where homing leaves the machine.
def _park_home(joint):
    return float(inifile.find("JOINT_%d" % joint, "HOME") or 0)


PARK_X, PARK_Y, PARK_Z = _park_home(0), _park_home(2), _park_home(3)
PARK_MOVES = ["G53 G0 Z%.3f" % PARK_Z, "G53 G0 X%.3f Y%.3f" % (PARK_X, PARK_Y)]

_park_cmd = linuxcnc.command()
_park_stat = linuxcnc.stat()


def _park_dialog(title, text, kind, default, *buttons):
    return int(root_window.tk.call("nf_dialog", ".error", title, text, kind, default, *buttons))


_park_was_on = False


def _park_watch_machine_on():
    global _park_was_on
    s = _park_stat
    s.poll()
    is_on = (not s.estop) and s.task_state == linuxcnc.STATE_ON
    if is_on and not _park_was_on and not all(s.homed[i] for i in range(s.joints)):
        _park_dialog(
            "Not homed",
            "Press Home All before jogging. The axes MOVE to their limit switches:\n\n"
            "  Z  up to its + limit\n"
            "  Y  to its Y- limit\n"
            "  X  both gantry sides to their X+ limits\n\n"
            "Keep clear of the gantry.",
            "warning", 0, "OK")
    _park_was_on = is_on
    root_window.after(500, _park_watch_machine_on)


def _park_can_move():
    s = _park_stat
    s.poll()
    if s.estop or s.task_state != linuxcnc.STATE_ON:
        return False
    if s.interp_state != linuxcnc.INTERP_IDLE:
        return False
    return all(s.homed[i] for i in range(s.joints))


def _park_close():
    root_window.destroy()


def _park_step(moves, when_done):
    s = _park_stat
    s.poll()
    if s.estop or s.task_state != linuxcnc.STATE_ON:
        _park_dialog("Park aborted", "Machine was switched off or E-stopped during the park move.",
                     "error", 0, "OK")
        return
    if s.interp_state != linuxcnc.INTERP_IDLE or not s.inpos:
        root_window.after(100, _park_step, moves, when_done)
        return
    if not moves:
        if when_done:
            when_done()
        return
    _park_cmd.mdi(moves[0])
    root_window.after(200, _park_step, moves[1:], when_done)


def _park_start(when_done=None):
    _park_cmd.mode(linuxcnc.MODE_MDI)
    _park_cmd.wait_complete()
    _park_step(list(PARK_MOVES), when_done)


def biesse_park(*args):
    if not _park_can_move():
        _park_dialog("Park", "Cannot park: machine must be on, homed and idle.", "warning", 0, "OK")
        return
    _park_start()


def biesse_quit(*args):
    if _park_can_move():
        choice = _park_dialog(
            "Close LinuxCNC",
            "Park before closing?\n\nRetract Z, then rapid X/Y to the home position\n"
            "(X %.1f, Y %.1f, Z %.1f).\nKeep clear of the gantry." % (PARK_X, PARK_Y, PARK_Z),
            "warning", 0, "Park and close", "Close without parking", "Cancel")
        if choice == 0:
            move = _park_dialog(
                "WARNING - MACHINE WILL MOVE",
                "THE MACHINE WILL MOVE NOW.\n\n"
                "Z rapids UP to %.1f, then X and Y rapid to X %.1f, Y %.1f.\n"
                % (PARK_Z, PARK_X, PARK_Y) +
                "Make sure the gantry path is clear and nobody is at the machine.",
                "warning", 1, "Move and close", "Cancel")
            if move == 0:
                _park_start(_park_close)
        elif choice == 1:
            _park_close()
    else:
        choice = _park_dialog(
            "Close LinuxCNC",
            "Machine is off, not homed or busy, so it will not be parked.\n\n"
            "Close LinuxCNC anyway?",
            "warning", 1, "Close", "Cancel")
        if choice == 0:
            _park_close()


root_window.protocol("WM_DELETE_WINDOW", biesse_quit)
root_window.tk.call(".menu.file", "entryconfigure", "end",
                    "-command", root_window.register(biesse_quit))

root_window.tk.call("button", ".toolbar.biesse_park", "-text", "Park",
                    "-command", root_window.register(biesse_park),
                    "-padx", 6, "-takefocus", 0)
root_window.tk.call("pack", ".toolbar.biesse_park", "-side", "left", "-padx", 8)

root_window.after(1000, _park_watch_machine_on)
