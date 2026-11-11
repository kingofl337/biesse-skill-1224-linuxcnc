# Biesse Skill 1224 - QtVCP handler for the "biesse_ui" screen.
# Page switching, MACHINE/WORK DRO toggle, zero/home/goto buttons, overrides,
# jog panel, offsets page, message log, run timer, RESET, Park and
# park-on-close. Axis-based throughout (X/Y/Z), so it works on the 3-joint
# simulator and on the 4-joint X gantry alike.

import os
import re
import time
import html
import hal
import linuxcnc
from PyQt5 import QtCore, QtWidgets
from qtvcp.core import Status, Action, Info
from qtvcp import logger

LOG = logger.getLogger(__name__)
STATUS = Status()
ACTION = Action()
INFO = Info()
# must match the scale the .ui and .qss were generated with (gen_biesse_ui.py)
UI_SCALE = float(INFO.INI.find("DISPLAY", "BIESSE_UI_SCALE") or 1)


def scaled(css):
    return re.sub(r"(\d+)(px|pt)", lambda m: "%d%s" % (max(1, round(int(m.group(1)) * UI_SCALE)),
                                                      m.group(2)), css)

AXES = ("X", "Y", "Z")
PAGES = ("run", "toolpath", "offsets", "tools", "messages", "config", "debug")
LOG_DIR = os.path.expanduser("~/linuxcnc/logs")
ALARM_COLOR = "#ff6b6b"

# CONFIG page: folder LOAD FILE opens in
PROGRAMS_SECTION = "BIESSE_PROGRAMS"
PROGRAM_FILTER = "G-code (*.ngc *.nc *.tap *.gcode *.txt);;All files (*)"

# TOOLS page: nominal diameter and diameter offset per tool live in the
# preferences; the tool table's D holds the effective diameter (used by G41/G42)
TOOLS_SECTION = "BIESSE_TOOLS"
TOOL_COLUMNS = ("Tool", "Diameter", "Height offset", "Diameter offset", "Effective diameter")

# DEBUG page: pins that do not exist in the running config are skipped
DEBUG_SECTION = "BIESSE_DEBUG"
DEBUG_PINS = (
    ["halui.machine.is-on", "iocontrol.0.emc-enable-in", "motion.probe-input",
     "nyx.0.ready", "nyx.0.error-cnt"]
    + ["nyx.0.servo-%02d.%s" % (s, p) for s in range(4)
       for p in ("online", "enabled", "alarm", "alarm-code", "in-00", "in-01", "in-02")]
    + ["joint.%d.%s" % (j, p) for j in range(4)
       for p in ("pos-fb", "f-error", "homed", "homing", "home-sw-in")]
    + ["spindle.0.speed-out", "spindle.0.forward"])
# CONFIG page: jog speed slider setting at start-up (mm/min)
JOG_SECTION = "BIESSE_JOG"

# FULL SPEED: X/Y speed (feeds, rapids and jogs) is capped at [BIESSE] LOCKED_MAX_FEED
# mm/min until unlocked with [BIESSE] FULL_SPEED_PASSWORD; locks again on E-stop
FULL_SPEED_STYLE = ("background: %s; color: #ffffff; border: 4px solid #ffffff;"
                    " border-radius: 6px; font-size: 15pt; font-weight: bold;")
FULL_SPEED_RED = scaled(FULL_SPEED_STYLE % "#d92d2d")
FULL_SPEED_GREEN = scaled(FULL_SPEED_STYLE % "#2e8b3e")
# JOG (keyboard jogging armed) flashes the same way
JOG_ARMED_STYLE = ("background: %s; color: #ffffff; border: 3px solid #ffffff;"
                   " border-radius: 6px; font-size: 13pt; font-weight: bold;")
JOG_ARMED_RED = scaled(JOG_ARMED_STYLE % "#d92d2d")
JOG_ARMED_GREEN = scaled(JOG_ARMED_STYLE % "#2e8b3e")

# CONFIG "Override limits": joint jogging while unhomed (no soft limits), capped speed
OVERRIDE_TITLE = "JOG - LIMITS OVERRIDDEN"
OVERRIDE_TITLE_STYLE = "color: #ff4d4d;"

# keyboard jogging: key -> (axis index, direction); Shift = fast jog at the speed limit
JOG_KEYS = {
    QtCore.Qt.Key_Left: (0, -1), QtCore.Qt.Key_Right: (0, 1),
    QtCore.Qt.Key_Down: (1, -1), QtCore.Qt.Key_Up: (1, 1),
    QtCore.Qt.Key_PageDown: (2, -1), QtCore.Qt.Key_PageUp: (2, 1),
}
# keys go to these widgets instead of jogging (typing, table navigation)
NO_JOG_WIDGETS = (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QAbstractItemView,
                  QtWidgets.QComboBox)

JOG_STEPS = (("cont", 0.0), ("001", 0.01), ("01", 0.1), ("1", 1.0), ("10", 10.0))
PAGE_HOOK = "/tmp/biesse_ui_page"
CALL_HOOK = "/tmp/biesse_ui_call"

# CONFIG page fields: (widget, preference key, default)
PROBE_SECTION = "BIESSE_TOOL_PROBE"
PROBE_FIELDS = (("cfg_probe_x", "Probe X", 0.0),
                ("cfg_probe_y", "Probe Y", 0.0),
                ("cfg_probe_start_z", "Start Z", -200.0),
                ("cfg_probe_max", "Max travel", 120.0),
                ("cfg_probe_fast", "Fast feed", 300.0),
                ("cfg_probe_slow", "Slow feed", 30.0),
                ("cfg_probe_retract", "Retract", 2.0))

RESET_ESTOP = scaled("background: #d92d2d; color: #ffffff; border: 6px solid #f2c94c;"
               " border-radius: 88px; font-size: 26pt; font-weight: bold;")
RESET_READY = scaled("background: #5a1414; color: #ffb3b3; border: 6px solid #d92d2d;"
               " border-radius: 88px; font-size: 26pt; font-weight: bold;")
MACHINE_ON_STYLE = scaled("background: #2e8b3e; color: #ffffff; border: 4px solid #7be08f;"
                    " border-radius: 6px; font-size: 15pt; font-weight: bold;")


class BiesseCloseFilter(QtCore.QObject):
    # Intercepts the main window's close so the handler can offer to park first.
    def __init__(self, handler):
        super().__init__()
        self.handler = handler

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Close and self.handler.close_requested():
            event.ignore()
            return True
        return False


class BiesseClickFilter(QtCore.QObject):
    # Any mouse press or touch outside the jog panel disarms keyboard jogging, and so
    # does the pointer leaving the main window (e.g. towards the desktop taskbar).
    def __init__(self, handler):
        super().__init__()
        self.handler = handler

    def eventFilter(self, obj, event):
        if event.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.TouchBegin) \
                and isinstance(obj, QtWidgets.QWidget):
            self.handler.screen_clicked(obj)
        elif event.type() == QtCore.QEvent.Leave and obj is self.handler.w:
            self.handler.set_jog_armed(False)
        return False


class HandlerClass:
    def __init__(self, halcomp, widgets, paths):
        self.h = halcomp
        self.w = widgets
        self.PATHS = paths
        self.stat = linuxcnc.stat()
        self.cmd = linuxcnc.command()
        self.reset_state = None
        self.machine_on_state = None
        self.run_seconds = 0
        self.closing = False

    # ------------------------------------------------------------ set up
    def initialized__(self):
        self.page_group = QtWidgets.QButtonGroup()
        for i, name in enumerate(PAGES):
            button = getattr(self.w, "btn_page_" + name)
            self.page_group.addButton(button, i)
        self.page_group.buttonClicked[int].connect(self.show_page)
        self.show_page(0)

        self.w.btn_machine.toggled.connect(self.show_machine_coords)
        self.show_machine_coords(False)

        for a in AXES:
            getattr(self.w, "btn_zero_" + a.lower()).clicked.connect(
                lambda _, a=a: self.mdi(["G10 L20 P0 %s0" % a]))
        self.w.btn_zero_all.clicked.connect(lambda: self.mdi(["G10 L20 P0 X0 Y0 Z0"]))
        self.w.btn_home_all.clicked.connect(self.home_all)

        self.w.btn_feed_minus.clicked.connect(lambda: self.nudge_feed(-10))
        self.w.btn_feed_plus.clicked.connect(lambda: self.nudge_feed(10))
        self.w.btn_spindle_minus.clicked.connect(lambda: self.nudge_spindle(-10))
        self.w.btn_spindle_plus.clicked.connect(lambda: self.nudge_spindle(10))

        self.w.btn_goto_zero.clicked.connect(
            lambda: self.mdi(["G53 G0 Z%.3f" % self.park_position()["Z"], "G0 X0 Y0"]))
        self.w.btn_safe_z.clicked.connect(
            lambda: self.mdi(["G53 G0 Z%.3f" % self.park_position()["Z"]]))
        self.w.btn_park.clicked.connect(self.park_clicked)
        for i in range(6):
            code = "G5%d" % (4 + i)
            getattr(self.w, "btn_g5%d" % (4 + i)).clicked.connect(
                lambda _, c=code: self.mdi([c]))
            getattr(self.w, "btn_off_g5%d" % (4 + i)).clicked.connect(
                lambda _, c=code: self.mdi([c]))

        self.w.btn_reload_file.clicked.connect(self.reload_file)
        self.w.btn_tp_reload.clicked.connect(self.reload_file)
        self.w.btn_load_file.clicked.connect(self.load_file)
        self.w.btn_tp_load.clicked.connect(self.load_file)
        self.load_program_dir()
        self.w.btn_cfg_browse_dir.clicked.connect(self.browse_program_dir)
        self.w.cfg_program_dir.editingFinished.connect(self.save_program_dir)

        # TOOLS page
        self.setup_tool_table()
        self.w.btn_tools_reload.clicked.connect(self.load_tool_table)
        self.w.btn_tools_apply.clicked.connect(self.apply_tool_table)
        self.w.btn_tools_add.clicked.connect(self.add_tool)

        # DEBUG page
        self.setup_debug_table()
        self.w.btn_debug_add.clicked.connect(self.debug_add_pin)
        self.w.debug_pin_name.returnPressed.connect(self.debug_add_pin)
        self.w.btn_debug_remove.clicked.connect(self.debug_remove_pin)

        # tool length sensor
        self.probe_ref = None
        self.load_probe_config()
        self.w.btn_tool_probe.clicked.connect(lambda: self.tool_probe(reference=False))
        self.w.btn_cfg_set_ref.clicked.connect(lambda: self.tool_probe(reference=True))
        self.w.btn_cfg_teach_xy.clicked.connect(self.teach_probe_xy)
        self.w.btn_cfg_goto_probe.clicked.connect(self.goto_probe)
        self.w.btn_cfg_save.clicked.connect(self.save_settings)

        self.w.btn_off_set_current.clicked.connect(lambda: self.mdi(["G10 L20 P0 X0 Y0 Z0"]))
        self.w.btn_off_clear_work.clicked.connect(lambda: self.mdi(["G10 L2 P0 X0 Y0 Z0"]))
        self.w.btn_off_clear_g92.clicked.connect(lambda: self.mdi(["G92.1"]))
        self.w.btn_off_clear_tool.clicked.connect(lambda: self.mdi(["G49"]))

        # jog panel
        self.setup_jog_panel()
        for i, a in enumerate(AXES):
            for sign, d in (("pos", 1), ("neg", -1)):
                b = getattr(self.w, "jog_%s_%s" % (a.lower(), sign))
                b.pressed.connect(lambda i=i, d=d: (self.set_jog_armed(True), self.jog(i, d)))
                b.released.connect(lambda i=i: self.jog_stop(i))

        # CONFIG "Override limits" (jog without homing, e.g. after a bad home)
        self.limits_override = False
        self.override_homed_seen = False
        self.override_max = float(INFO.INI.find("BIESSE", "OVERRIDE_JOG_MAX") or 2000)
        self.w.cfg_override_limits.clicked.connect(self.override_clicked)

        # speed cap and the FULL SPEED button
        self.locked_feed = float(INFO.INI.find("BIESSE", "LOCKED_MAX_FEED") or 10000)
        self.full_speed_password = INFO.INI.find("BIESSE", "FULL_SPEED_PASSWORD") or ""
        self.full_speed = False
        self.flash_on = False
        self.flash_timer = QtCore.QTimer()
        self.flash_timer.timeout.connect(self.flash_full_speed)
        self.w.btn_full_speed.clicked.connect(self.full_speed_clicked)
        self.set_full_speed(False, quiet=True)
        self.load_jog_default()

        # keyboard jogging, only while JOG is armed (JOG or an on-screen jog button
        # clicked); a click outside the jog panel or any other key disarms it.
        # Key jogs also stop if the window loses focus (no key release then).
        self.held_jog_keys = {}
        self.jog_armed = False
        self.jog_flash_on = False
        self.jog_flash_timer = QtCore.QTimer()
        self.jog_flash_timer.timeout.connect(self.flash_jog)
        self.w.jog_enable.clicked.connect(self.set_jog_armed)
        self.click_filter = BiesseClickFilter(self)
        QtWidgets.QApplication.instance().installEventFilter(self.click_filter)
        QtWidgets.QApplication.instance().applicationStateChanged.connect(
            lambda state: state == QtCore.Qt.ApplicationActive or self.set_jog_armed(False))

        # alarms and messages: one-line bar on RUN, full logs on MESSAGES
        self.unseen_alarms = 0
        self.last_message = ("", False)
        STATUS.connect('error', self.add_message)
        self.w.btn_last_message.clicked.connect(lambda: self.show_page(PAGES.index("messages")))
        for key in ("alarms", "messages"):
            getattr(self.w, "btn_%s_save" % key).clicked.connect(lambda _, k=key: self.save_log(k))
            getattr(self.w, "btn_%s_clear" % key).clicked.connect(lambda _, k=key: self.clear_log(k))
        self.w.btn_runtime_zero.clicked.connect(self.zero_runtime)

        self.w.btn_reset.clicked.connect(self.reset_clicked)
        STATUS.connect('state-on', lambda w: QtCore.QTimer.singleShot(300, self.startup_prompts))
        STATUS.connect('tool-in-spindle-changed', lambda w, tool: self.remember_tool(tool))
        self.tool_asked = False
        # tool from the start-up prompt: MDI is refused until homed, so set it then
        self.pending_tool = None
        STATUS.connect('all-homed', lambda w: self.apply_pending_tool())

        self.close_filter = BiesseCloseFilter(self)
        self.w.installEventFilter(self.close_filter)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)
        self.clock = QtCore.QTimer()
        self.clock.timeout.connect(self.tick)
        self.clock.start(1000)
        self.refresh()

    def closing_cleanup__(self):
        pass

    # ------------------------------------------------------------ helpers
    def poll(self):
        self.stat.poll()
        return self.stat

    def all_homed(self):
        s = self.poll()
        return all(s.homed[j] for j in range(s.joints))

    def machine_ready(self):
        s = self.poll()
        return not s.estop and s.task_state == linuxcnc.STATE_ON

    def mdi(self, commands, when_done=None):
        # run MDI lines one after another, each once the previous finished
        if not self.machine_ready():
            self.add_message(None, "error", "Machine must be ON for that command.")
            return
        self.cmd.mode(linuxcnc.MODE_MDI)
        self.cmd.wait_complete()
        self.mdi_step(list(commands), when_done)

    def mdi_step(self, commands, when_done):
        s = self.poll()
        if s.estop or s.task_state != linuxcnc.STATE_ON:
            self.add_message(None, "error", "Stopped: machine switched off or E-stopped.")
            return
        if s.interp_state != linuxcnc.INTERP_IDLE or not s.inpos:
            QtCore.QTimer.singleShot(100, lambda: self.mdi_step(commands, when_done))
            return
        if not commands:
            if when_done:
                when_done()
            return
        if callable(commands[0]):
            # a check between G-code lines: returning False stops the sequence
            if commands[0]() is False:
                return
            self.mdi_step(commands[1:], when_done)
            return
        self.cmd.mdi(commands[0])
        QtCore.QTimer.singleShot(200, lambda: self.mdi_step(commands[1:], when_done))

    def add_message(self, w, kind, text):
        # every LinuxCNC error / message lands here (pop-up notifications are off);
        # errors go to the ALARMS log, the rest to MESSAGES; the newest is shown on RUN
        error = kind in (linuxcnc.NML_ERROR, linuxcnc.OPERATOR_ERROR, "error")
        stamped = time.strftime("%H:%M:%S  ") + " ".join(str(text).split())
        line = html.escape(time.strftime("%H:%M:%S  ") + str(text).strip()).replace("\n", "<br>")
        log = self.w.alarms_log if error else self.w.messages_log
        log.appendHtml('<span style="color:%s">%s</span>' % (ALARM_COLOR if error else "#ffffff", line))
        if error and PAGES[self.w.stack_pages.currentIndex()] != "messages":
            self.unseen_alarms += 1
            self.show_alarm_count()
        self.last_message = (stamped, error)
        self.show_last_message()

    def show_last_message(self):
        text, error = self.last_message
        b = self.w.btn_last_message
        b.setText(b.fontMetrics().elidedText(text, QtCore.Qt.ElideRight, max(b.width() - 24, 50)))
        b.setStyleSheet("color: %s;" % ALARM_COLOR if error else "")

    def show_alarm_count(self):
        b = self.w.btn_page_messages
        if self.unseen_alarms:
            b.setText("MESSAGES (%d)" % self.unseen_alarms)
            b.setStyleSheet("background: #d92d2d; border: 2px solid #ffffff;")
        else:
            b.setText("MESSAGES")
            b.setStyleSheet("")

    def save_log(self, key):
        os.makedirs(LOG_DIR, exist_ok=True)
        default = os.path.join(LOG_DIR, "%s-%s.txt" % (key, time.strftime("%Y%m%d-%H%M%S")))
        dialog = QtWidgets.QFileDialog(self.w, "Save " + key, LOG_DIR, "Text files (*.txt);;All files (*)")
        dialog.setOption(QtWidgets.QFileDialog.DontUseNativeDialog)
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        dialog.selectFile(default)
        dialog.resize(round(1200 * UI_SCALE), round(800 * UI_SCALE))
        if dialog.exec_():
            self.write_log(key, dialog.selectedFiles()[0])

    def write_log(self, key, path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(getattr(self.w, key + "_log").toPlainText() + "\n")
        except OSError as e:
            self.add_message(None, "error", "Save %s failed: %s" % (key, e))
            return
        self.add_message(None, None, "Saved %s to %s" % (key, path))

    def clear_log(self, key):
        getattr(self.w, key + "_log").clear()
        if key == "alarms":
            self.unseen_alarms = 0
            self.show_alarm_count()
            if self.last_message[1]:
                self.last_message = ("", False)
                self.show_last_message()

    # ------------------------------------------------------------ pages
    def show_page(self, index):
        self.w.stack_pages.setCurrentIndex(index)
        self.page_group.button(index).setChecked(True)
        if PAGES[index] == "tools" and hasattr(self.w, "tool_table"):
            self.load_tool_table()
        if PAGES[index] == "messages":
            self.unseen_alarms = 0
            self.show_alarm_count()
        host = self.w.host_graphics_tp if PAGES[index] == "toolpath" else self.w.host_graphics_run
        if self.w.gcodegraphics.parent() is not host:
            host.layout().addWidget(self.w.gcodegraphics)

    def show_machine_coords(self, machine):
        for a in AXES:
            getattr(self.w, "dro_mach_" + a.lower()).setVisible(machine)
            getattr(self.w, "dro_work_" + a.lower()).setVisible(not machine)
        self.w.btn_machine.setText("M\nA\nC\nH" if machine else "W\nO\nR\nK")

    # ------------------------------------------------------------ overrides
    def nudge_feed(self, step):
        s = self.poll()
        ACTION.SET_FEED_RATE(max(0, min(150, round(s.feedrate * 100) + step)))

    def nudge_spindle(self, step):
        s = self.poll()
        ACTION.SET_SPINDLE_RATE(max(50, min(100, round(s.spindle[0]['override'] * 100) + step)))

    # ------------------------------------------------------------ jog
    def setup_jog_panel(self):
        # step buttons: CONT = continuous while held, otherwise one step per press
        self.jog_increment = 0.0
        self.jog_step_group = QtWidgets.QButtonGroup()
        for key, step in JOG_STEPS:
            b = getattr(self.w, "jog_step_" + key)
            self.jog_step_group.addButton(b)
            b.clicked.connect(lambda _, step=step: self.set_jog_step(step))
        self.w.jog_step_cont.setChecked(True)
        # speed slider in mm/min, up to the [DISPLAY] maximum
        max_rate = float(INFO.INI.find("DISPLAY", "MAX_LINEAR_VELOCITY") or 25) * 60
        self.jog_max_rate = max_rate
        default = float(INFO.INI.find("DISPLAY", "DEFAULT_LINEAR_VELOCITY") or 10) * 60
        s = self.w.jog_speed
        s.setOrientation(QtCore.Qt.Horizontal)
        s.setRange(60, int(max_rate))
        s.setSingleStep(60)
        s.setPageStep(600)
        s.valueChanged.connect(lambda v: self.w.lbl_jog_speed.setText("%d mm/min" % v))
        s.setValue(int(min(max(default, 60), max_rate)))
        self.w.lbl_jog_speed.setText("%d mm/min" % s.value())

    def load_jog_default(self):
        p = self.prefs()
        default = float(INFO.INI.find("BIESSE", "DEFAULT_JOG") or 2000)
        rate = p.getpref("Default speed", default, float, JOG_SECTION) if p else default
        self.w.cfg_jog_default.setText("%.0f" % rate)
        self.w.jog_speed.setValue(int(rate))

    def save_jog_default(self):
        try:
            rate = float(self.w.cfg_jog_default.text())
        except ValueError:
            rate = 0
        if rate < 60:
            self.add_message(None, "error", "Default jog speed: enter at least 60 mm/min.")
            return False
        p = self.prefs()
        if p:
            p.putpref("Default speed", rate, float, JOG_SECTION)
        self.w.jog_speed.setValue(int(rate))
        self.add_message(None, None, "Default jog speed %.0f mm/min saved." % rate)
        return True

    # ------------------------------------------------------------ speed cap
    def speed_limit(self):
        # X/Y speed limit in mm/min
        traj_max = float(INFO.INI.find("TRAJ", "MAX_LINEAR_VELOCITY") or 25) * 60
        return traj_max if self.full_speed else min(self.locked_feed, traj_max)

    def set_full_speed(self, on, quiet=False):
        self.full_speed = on
        self.cmd.maxvel(self.speed_limit() / 60)
        self.w.jog_speed.setMaximum(int(min(self.speed_limit(), self.jog_max_rate)))
        if on:
            self.flash_timer.start(500)
            self.flash_full_speed()
        else:
            self.flash_timer.stop()
            self.w.btn_full_speed.setStyleSheet("")
        if not quiet:
            self.add_message(None, None, "FULL SPEED unlocked: X/Y up to %.0f mm/min." % self.speed_limit()
                             if on else "X/Y speed limited to %.0f mm/min." % self.speed_limit())

    def flash_full_speed(self):
        # 1 Hz red/green while full speed is unlocked
        self.flash_on = not self.flash_on
        self.w.btn_full_speed.setStyleSheet(FULL_SPEED_RED if self.flash_on else FULL_SPEED_GREEN)

    def full_speed_clicked(self):
        if self.full_speed:
            self.set_full_speed(False)
            return
        if not self.full_speed_password:
            self.add_message(None, "error", "FULL SPEED: no [BIESSE] FULL_SPEED_PASSWORD in the INI.")
            return
        if self.poll().task_state == linuxcnc.STATE_ESTOP:
            self.add_message(None, None, "FULL SPEED: press RESET first (E-stop keeps the speed limit).")
            return
        text, ok = QtWidgets.QInputDialog.getText(
            self.w, "Full speed", "Password for X/Y speeds above %.0f mm/min:" % self.locked_feed,
            QtWidgets.QLineEdit.Password)
        if not ok:
            return
        if text == self.full_speed_password:
            self.set_full_speed(True)
        else:
            self.add_message(None, "error", "FULL SPEED: wrong password.")

    def set_jog_step(self, step):
        self.jog_increment = step

    def jog(self, axis, direction, fast=None):
        # slider speed; Shift (held on the keyboard) = fast jog at the speed limit
        if not self.machine_ready():
            return
        if fast is None:
            fast = bool(QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier)
        rate = min(self.speed_limit(), self.jog_max_rate) if fast else self.w.jog_speed.value()
        if self.limits_override:
            self.joint_jog(axis, direction, min(rate, self.override_max))
            return
        if not self.all_homed():
            # unhomed jogging addresses joints, which on the gantry would move one X side
            self.add_message(None, None, "Press HOME ALL before jogging (or Override limits on CONFIG).")
            return
        ACTION.SET_MANUAL_MODE()
        ACTION.JOG(axis, direction, rate / 60, self.jog_increment)

    # ------------------------------------------------------------ limits override
    def axis_joints(self, axis):
        # joints driving an axis, from [KINS] coordinates= (X -> both gantry joints)
        kins = INFO.INI.find("KINS", "KINEMATICS") or ""
        coords = "XYZ"
        for part in kins.split():
            if part.startswith("coordinates="):
                coords = part.split("=", 1)[1].upper()
        return [j for j, a in enumerate(coords) if a == AXES[axis]]

    def joint_jog(self, axis, direction, rate):
        # joint-mode jog, all joints of the axis together (no soft limits while unhomed)
        if self.poll().task_mode != linuxcnc.MODE_MANUAL:
            self.cmd.mode(linuxcnc.MODE_MANUAL)
            self.cmd.wait_complete()
        self.cmd.teleop_enable(0)
        for j in self.axis_joints(axis):
            if self.jog_increment > 0:
                self.cmd.jog(linuxcnc.JOG_INCREMENT, True, j, direction * rate / 60, self.jog_increment)
            else:
                self.cmd.jog(linuxcnc.JOG_CONTINUOUS, True, j, direction * rate / 60)

    def stop_axis(self, axis):
        if self.limits_override:
            for j in self.axis_joints(axis):
                self.cmd.jog(linuxcnc.JOG_STOP, True, j)
        else:
            ACTION.JOG(axis, 0, 0, 0)

    def gantry_sequence(self, synchronized):
        # LinuxCNC refuses unhomed jogging of joints with a negative (synchronized)
        # HOME_SEQUENCE, i.e. the X gantry pair. During the override their sequence is
        # made positive through the ini.N.home_sequence pins and restored before homing.
        for j in self.axis_joints(0):
            seq = int(INFO.INI.find("JOINT_%d" % j, "HOME_SEQUENCE") or 0)
            if seq < 0:
                hal.set_p("ini.%d.home_sequence" % j, str(seq if synchronized else -seq))

    def home_all(self):
        if self.limits_override:
            # put the gantry's synchronized home sequence back first
            self.set_limits_override(False)
            QtCore.QTimer.singleShot(500, lambda: ACTION.SET_MACHINE_HOMING(-1))
        else:
            ACTION.SET_MACHINE_HOMING(-1)

    def override_clicked(self, checked):
        if not checked:
            self.set_limits_override(False)
            return
        if not self.machine_ready() or self.poll().interp_state != linuxcnc.INTERP_IDLE:
            self.add_message(None, "error", "Override limits: machine must be on and idle.")
            self.w.cfg_override_limits.setChecked(False)
            return
        s = self.poll()
        if any(s.homed[j] for j in range(s.joints)):
            box = QtWidgets.QMessageBox(self.w)
            box.setWindowTitle("Override limits")
            box.setIcon(QtWidgets.QMessageBox.Warning)
            box.setText("Override limits UNHOMES the machine.\n\n"
                        "Jogging then has no soft limits (the drives still stop on their\n"
                        "limit switches) and is limited to %.0f mm/min.\n"
                        "Press HOME before running any program." % self.override_max)
            ok = box.addButton("Unhome and override", QtWidgets.QMessageBox.AcceptRole)
            box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
            box.exec_()
            if box.clickedButton() != ok:
                self.w.cfg_override_limits.setChecked(False)
                return
            if self.poll().task_mode != linuxcnc.MODE_MANUAL:
                self.cmd.mode(linuxcnc.MODE_MANUAL)
                self.cmd.wait_complete()
            self.cmd.teleop_enable(0)
            self.cmd.wait_complete()
            self.cmd.unhome(-1)
        self.set_limits_override(True)

    def set_limits_override(self, on):
        if self.limits_override == on:
            self.w.cfg_override_limits.setChecked(on)
            return
        self.stop_key_jogs()
        self.limits_override = on
        self.override_homed_seen = False
        self.gantry_sequence(synchronized=not on)
        self.w.cfg_override_limits.setChecked(on)
        self.w.lbl_jog_title.setText(OVERRIDE_TITLE if on else "JOG")
        self.w.lbl_jog_title.setStyleSheet(OVERRIDE_TITLE_STYLE if on else "")
        self.add_message(None, "error" if on else None,
                         "Limits OVERRIDDEN: unhomed joint jogging, max %.0f mm/min." % self.override_max
                         if on else "Limits override off.")

    def processed_key_event__(self, receiver, event, is_pressed, key, code, shift, cntrl):
        # called by qtvcp for every key event; True = consumed
        if code not in JOG_KEYS:
            # any other key (Shift alone excepted: it selects fast jog) disarms JOG
            if is_pressed and self.jog_armed and code != QtCore.Qt.Key_Shift:
                self.set_jog_armed(False)
            return False
        if not self.jog_armed:
            return False
        if QtWidgets.QApplication.activeModalWidget() is not None:
            return False
        if isinstance(receiver, QtWidgets.QWidget) and (
                receiver.window() is not self.w or isinstance(receiver, NO_JOG_WIDGETS)):
            return False
        if event.isAutoRepeat():
            return True
        axis, direction = JOG_KEYS[code]
        if is_pressed:
            if code not in self.held_jog_keys:
                self.held_jog_keys[code] = axis
                self.jog(axis, direction, fast=shift)
        elif self.held_jog_keys.pop(code, None) is not None:
            self.jog_stop(axis)
        return True

    def processed_focus_event__(self, receiver, event):
        pass

    def set_jog_armed(self, on):
        if not on and not self.jog_armed and not self.held_jog_keys:
            return
        was_armed = self.jog_armed
        self.jog_armed = bool(on)
        self.w.jog_enable.setChecked(self.jog_armed)
        if self.jog_armed and not was_armed:
            # 1 Hz red/green while armed, like FULL SPEED
            self.jog_flash_timer.start(500)
            self.flash_jog()
        elif not self.jog_armed:
            self.jog_flash_timer.stop()
            self.w.jog_enable.setStyleSheet("")
            self.stop_key_jogs()

    def flash_jog(self):
        self.jog_flash_on = not self.jog_flash_on
        self.w.jog_enable.setStyleSheet(JOG_ARMED_RED if self.jog_flash_on else JOG_ARMED_GREEN)

    def screen_clicked(self, widget):
        if self.jog_armed and widget is not self.w.frame_jog \
                and not self.w.frame_jog.isAncestorOf(widget):
            self.set_jog_armed(False)

    def stop_key_jogs(self):
        for axis in self.held_jog_keys.values():
            self.stop_axis(axis)
        self.held_jog_keys = {}

    def jog_stop(self, axis):
        if self.jog_increment == 0:
            self.stop_axis(axis)

    # ------------------------------------------------------------ file
    def default_program_dir(self):
        prefix = getattr(INFO, "PROGRAM_PREFIX", None) or "~/linuxcnc/nc_files"
        return os.path.expanduser(prefix)

    def load_program_dir(self):
        p = self.prefs()
        folder = p.getpref("Programs folder", self.default_program_dir(), str,
                           PROGRAMS_SECTION) if p else self.default_program_dir()
        self.w.cfg_program_dir.setText(folder)

    def save_program_dir(self):
        folder = os.path.expanduser(self.w.cfg_program_dir.text().strip())
        if not os.path.isdir(folder):
            self.add_message(None, "error", "Programs folder not found: %s" % folder)
            return
        p = self.prefs()
        if p:
            p.putpref("Programs folder", folder, str, PROGRAMS_SECTION)

    def browse_program_dir(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self.w, "Programs folder", self.program_dir(),
            QtWidgets.QFileDialog.ShowDirsOnly | QtWidgets.QFileDialog.DontUseNativeDialog)
        if folder:
            self.w.cfg_program_dir.setText(folder)
            self.save_program_dir()
            self.add_message(None, None, "Programs folder set to %s" % folder)

    def program_dir(self):
        folder = os.path.expanduser(self.w.cfg_program_dir.text().strip())
        return folder if os.path.isdir(folder) else self.default_program_dir()

    def load_file(self):
        s = self.poll()
        if s.interp_state != linuxcnc.INTERP_IDLE:
            self.add_message(None, "error", "Load file: wait until the machine is idle.")
            return
        dialog = QtWidgets.QFileDialog(self.w, "Load program", self.program_dir(), PROGRAM_FILTER)
        dialog.setOption(QtWidgets.QFileDialog.DontUseNativeDialog)
        dialog.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        dialog.resize(round(1200 * UI_SCALE), round(800 * UI_SCALE))
        if dialog.exec_() and dialog.selectedFiles():
            path = dialog.selectedFiles()[0]
            ACTION.OPEN_PROGRAM(path)
            self.add_message(None, None, "Loaded %s" % path)

    def reload_file(self):
        f = self.poll().file
        if f:
            ACTION.OPEN_PROGRAM(f)

    # ------------------------------------------------------------ periodic
    def refresh(self):
        s = self.poll()
        g5x = s.g5x_index
        for i in range(6):
            on = (g5x == i + 1)
            getattr(self.w, "btn_g5%d" % (4 + i)).setChecked(on)
            getattr(self.w, "btn_off_g5%d" % (4 + i)).setChecked(on)
        self.w.lbl_active_fixture.setText("Active fixture: G5%d" % (3 + g5x))
        for i, a in enumerate(AXES):
            getattr(self.w, "off_work_" + a.lower()).setText("%.4f" % s.g5x_offset[i])
            getattr(self.w, "off_g92_" + a.lower()).setText("%.4f" % s.g92_offset[i])
        self.w.off_tool_z.setText("%.4f" % s.tool_offset[2])
        self.reset_style(s.task_state == linuxcnc.STATE_ESTOP)
        # CYCLE STOP must always work out of E-stop (qtvcp's own enable logic left it
        # disabled after RESET); abort is safe in any state
        self.w.btn_cycle_stop.setEnabled(s.task_state != linuxcnc.STATE_ESTOP)
        # speed cap: lock again on E-stop, and keep LinuxCNC's max velocity at the limit
        if s.task_state == linuxcnc.STATE_ESTOP and self.full_speed:
            self.set_full_speed(False)
        elif abs(s.max_velocity * 60 - self.speed_limit()) > 1:
            self.cmd.maxvel(self.speed_limit() / 60)
        if s.task_state != linuxcnc.STATE_ON and self.jog_armed:
            self.set_jog_armed(False)
        # limits override: off at E-stop / machine off, and once homing has finished
        if self.limits_override:
            all_homed = all(s.homed[j] for j in range(s.joints))
            if s.task_state != linuxcnc.STATE_ON:
                self.set_limits_override(False)
            elif not all_homed:
                self.override_homed_seen = True
            elif self.override_homed_seen:
                self.set_limits_override(False)
        machine_on = (s.task_state == linuxcnc.STATE_ON)
        if machine_on != self.machine_on_state:
            self.machine_on_state = machine_on
            self.w.btn_machine_on.setStyleSheet(MACHINE_ON_STYLE if machine_on else "")
            self.w.btn_machine_on.setText("MACHINE\nON" if machine_on else "MACHINE\nOFF")
        if self.w.stack_pages.currentIndex() == PAGES.index("debug"):
            self.refresh_debug()

    def tick(self):
        # test hook: "echo 1 > /tmp/biesse_ui_page" switches page (used for screenshots)
        if os.path.exists(PAGE_HOOK):
            try:
                with open(PAGE_HOOK) as f:
                    self.show_page(int(f.read().strip()))
            except (ValueError, IndexError):
                pass
            os.remove(PAGE_HOOK)
        # test hook: "echo tool_probe 1 > /tmp/biesse_ui_call" calls a handler method
        if os.path.exists(CALL_HOOK):
            with open(CALL_HOOK) as f:
                parts = f.read().split()
            os.remove(CALL_HOOK)
            if parts and hasattr(self, parts[0]):
                getattr(self, parts[0])(*[int(a) for a in parts[1:]])
        s = self.poll()
        if s.task_mode == linuxcnc.MODE_AUTO and s.interp_state != linuxcnc.INTERP_IDLE \
                and not s.paused:
            self.run_seconds += 1
        h, m = divmod(self.run_seconds, 3600)
        m, sec = divmod(m, 60)
        self.w.lbl_runtime.setText("%02d:%02d:%02d" % (h, m, sec))

    def test_mdi_line(self):
        # test hook target: type a line into the MDI box and submit it like Enter
        self.add_message(None, None, "Test: MDI line enabled = %s" % self.w.mdiline.isEnabled())
        self.w.mdiline.setText("G53 G0 X-100 Y-900 Z-10")
        self.w.mdiline.submit()

    def test_open_warmup(self):
        # test hook target
        ACTION.OPEN_PROGRAM(os.path.expanduser("~/linuxcnc/nc_files/xy-warmup.ngc"))

    def test_messages(self):
        # test hook target: one alarm, one message, then save both logs
        self.add_message(None, "error", "Test alarm: following error on joint 2")
        self.add_message(None, None, "Test message: hello from the test hook")
        self.write_log("alarms", os.path.join(LOG_DIR, "test-alarms.txt"))
        self.write_log("messages", os.path.join(LOG_DIR, "test-messages.txt"))

    def test_full_speed(self, on):
        # test hook target: unlock (1) / lock (0) without the password dialog
        self.set_full_speed(bool(on))

    def test_cycle_start(self):
        # test hook target: press the CYCLE START button
        self.w.btn_cycle_start.click()

    def zero_runtime(self):
        self.run_seconds = 0
        self.tick()

    # ------------------------------------------------------------ reset
    def reset_style(self, estopped):
        if estopped == self.reset_state:
            return
        self.reset_state = estopped
        self.w.btn_reset.setStyleSheet(RESET_ESTOP if estopped else RESET_READY)

    def reset_clicked(self):
        if self.poll().task_state == linuxcnc.STATE_ESTOP:
            ACTION.SET_ESTOP_STATE(False)
            ACTION.SET_MACHINE_STATE(True)
        else:
            ACTION.SET_ESTOP_STATE(True)

    def startup_prompts(self):
        # at machine-on: home reminder, then (once per session) which tool is loaded
        self.home_reminder()
        if not self.tool_asked:
            self.tool_asked = True
            self.ask_tool_in_spindle()

    def remember_tool(self, tool):
        p = self.prefs()
        if p:
            p.putpref("Last tool", int(tool), int, TOOLS_SECTION)

    def ask_tool_in_spindle(self):
        p = self.prefs()
        last = p.getpref("Last tool", 0, int, TOOLS_SECTION) if p else 0
        tool, ok = QtWidgets.QInputDialog.getInt(
            self.w, "Tool in spindle", "Which tool is in the spindle?  (0 = none)",
            last, 0, 999)
        if not ok:
            return
        self.remember_tool(tool)
        if self.all_homed():
            self.set_tool_in_spindle(tool)
        else:
            self.pending_tool = tool
            self.add_message(None, None, "Tool %d will be set in the spindle after homing." % tool)

    def set_tool_in_spindle(self, tool):
        self.pending_tool = None
        self.mdi(["M61 Q%d" % tool, "G43" if tool > 0 else "G49"])
        self.add_message(None, None, "Tool in spindle set to %d." % tool)

    def apply_pending_tool(self):
        if self.pending_tool is not None:
            tool = self.pending_tool
            QtCore.QTimer.singleShot(500, lambda: self.set_tool_in_spindle(tool))

    def home_reminder(self):
        if self.all_homed():
            return
        self.add_message(None, "error", "Not homed: press HOME ALL before jogging.")
        QtWidgets.QMessageBox.warning(
            self.w, "Not homed",
            "Press HOME ALL before jogging. The axes MOVE to their home switches:\n\n"
            "  Z  up, near the top\n"
            "  Y  towards the Y- end\n"
            "  X  both gantry sides towards the X+ end\n\n"
            "Keep clear of the gantry.")

    # ------------------------------------------------------------ tools page
    def setup_tool_table(self):
        t = self.w.tool_table
        t.setColumnCount(len(TOOL_COLUMNS))
        t.setHorizontalHeaderLabels(TOOL_COLUMNS)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        t.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        t.verticalHeader().setDefaultSectionSize(44)
        self.load_tool_table()

    def tool_pref(self, tool, key, default):
        p = self.prefs()
        return p.getpref("T%d %s" % (tool, key), default, float, TOOLS_SECTION) if p else default

    def load_tool_table(self):
        s = self.poll()
        tools = {}
        for entry in s.tool_table:
            if entry.id > 0 and entry.id not in tools:
                tools[entry.id] = entry
        t = self.w.tool_table
        t.setRowCount(len(tools))
        for row, tool in enumerate(sorted(tools)):
            entry = tools[tool]
            offset = self.tool_pref(tool, "dia offset", 0.0)
            nominal = self.tool_pref(tool, "diameter", entry.diameter - offset)
            values = (str(tool), "%.4f" % nominal, "%.4f" % entry.zoffset, "%.4f" % offset,
                      "%.4f" % (nominal + offset))
            for col, text in enumerate(values):
                item = QtWidgets.QTableWidgetItem(text)
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                if col in (0, 4):
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                t.setItem(row, col, item)

    def apply_tool_table(self):
        if not self.machine_ready():
            self.add_message(None, "error", "Tools: switch the machine on to write the tool table.")
            return
        t = self.w.tool_table
        commands = []
        p = self.prefs()
        try:
            for row in range(t.rowCount()):
                tool = int(t.item(row, 0).text())
                nominal = float(t.item(row, 1).text())
                height = float(t.item(row, 2).text())
                offset = float(t.item(row, 3).text())
                if p:
                    p.putpref("T%d diameter" % tool, nominal, float, TOOLS_SECTION)
                    p.putpref("T%d dia offset" % tool, offset, float, TOOLS_SECTION)
                commands.append("G10 L1 P%d Z%.4f R%.4f" % (tool, height, (nominal + offset) / 2))
        except (ValueError, AttributeError):
            self.add_message(None, "error", "Tools: every value must be a number.")
            return
        commands.append(lambda: QtCore.QTimer.singleShot(500, self.load_tool_table) or True)
        self.mdi(commands)
        self.add_message(None, None, "Tool table updated (%d tools)." % (len(commands) - 1))

    def add_tool(self):
        tool, ok = QtWidgets.QInputDialog.getInt(self.w, "Add tool", "Tool number:", 1, 1, 999)
        if not ok:
            return
        if not self.machine_ready():
            self.add_message(None, "error", "Tools: switch the machine on to add a tool.")
            return
        self.mdi(["G10 L1 P%d Z0 R0" % tool,
                  lambda: QtCore.QTimer.singleShot(500, self.load_tool_table) or True])

    # ------------------------------------------------------------ debug page
    def setup_debug_table(self):
        t = self.w.debug_table
        t.setColumnCount(2)
        t.setHorizontalHeaderLabels(("Pin", "Value"))
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        t.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        t.verticalHeader().setDefaultSectionSize(32)
        p = self.prefs()
        extra = p.getpref("Extra pins", "", str, DEBUG_SECTION) if p else ""
        self.debug_pins = []
        for name in list(DEBUG_PINS) + [n for n in extra.split(",") if n]:
            self.debug_add(name, quiet=True)

    def debug_value(self, name):
        try:
            return hal.get_value(name)
        except Exception:
            return None

    def debug_add(self, name, quiet=False):
        name = name.strip()
        if not name or name in self.debug_pins:
            return False
        if self.debug_value(name) is None:
            if not quiet:
                self.add_message(None, "error", "Debug: no HAL pin or signal named %s." % name)
            return False
        self.debug_pins.append(name)
        t = self.w.debug_table
        row = t.rowCount()
        t.insertRow(row)
        t.setItem(row, 0, QtWidgets.QTableWidgetItem(name))
        t.setItem(row, 1, QtWidgets.QTableWidgetItem(""))
        return True

    def save_debug_pins(self):
        p = self.prefs()
        if p:
            extra = [n for n in self.debug_pins if n not in DEBUG_PINS]
            p.putpref("Extra pins", ",".join(extra), str, DEBUG_SECTION)

    def debug_add_pin(self):
        if self.debug_add(self.w.debug_pin_name.text()):
            self.w.debug_pin_name.clear()
            self.save_debug_pins()

    def debug_remove_pin(self):
        rows = sorted({i.row() for i in self.w.debug_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.w.debug_table.removeRow(row)
            del self.debug_pins[row]
        self.save_debug_pins()

    def refresh_debug(self):
        t = self.w.debug_table
        for row, name in enumerate(self.debug_pins):
            value = self.debug_value(name)
            if isinstance(value, bool):
                text = "TRUE" if value else "FALSE"
            elif isinstance(value, float):
                text = "%.4f" % value
            else:
                text = str(value)
            item = t.item(row, 1)
            if item.text() != text:
                item.setText(text)
                item.setForeground(QtCore.Qt.green if value is True else
                                   QtCore.Qt.white)

    # ------------------------------------------------------------ tool probe
    def prefs(self):
        return getattr(self.w, "PREFS_", None)

    def load_probe_config(self):
        p = self.prefs()
        for name, key, default in PROBE_FIELDS:
            value = p.getpref(key, default, float, PROBE_SECTION) if p else default
            getattr(self.w, name).setText("%.3f" % value)
        if p and p.getpref("Reference set", False, bool, PROBE_SECTION):
            self.probe_ref = p.getpref("Reference Z", 0.0, float, PROBE_SECTION)
        self.show_probe_ref()

    def show_probe_ref(self):
        self.w.cfg_probe_ref.setText("not measured" if self.probe_ref is None
                                     else "%.4f" % self.probe_ref)

    def probe_value(self, name):
        return float(getattr(self.w, name).text())

    def save_settings(self):
        # CONFIG page SAVE SETTINGS
        if self.save_jog_default():
            self.save_probe_config()

    def save_probe_config(self):
        try:
            values = [(key, self.probe_value(name)) for name, key, _ in PROBE_FIELDS]
        except ValueError:
            self.add_message(None, None, "Probe settings: every field must be a number.")
            return False
        p = self.prefs()
        if p:
            for key, value in values:
                p.putpref(key, value, float, PROBE_SECTION)
            p.putpref("Reference set", self.probe_ref is not None, bool, PROBE_SECTION)
            p.putpref("Reference Z", self.probe_ref or 0.0, float, PROBE_SECTION)
        self.add_message(None, None, "Probe settings saved.")
        return True

    def teach_probe_xy(self):
        s = self.poll()
        self.w.cfg_probe_x.setText("%.3f" % s.actual_position[0])
        self.w.cfg_probe_y.setText("%.3f" % s.actual_position[1])
        self.save_probe_config()

    def goto_probe(self):
        if not self.save_probe_config():
            return
        safe = self.park_position()["Z"]
        self.mdi(["G53 G0 Z%.3f" % safe,
                  "G53 G0 X%.3f Y%.3f" % (self.probe_value("cfg_probe_x"),
                                          self.probe_value("cfg_probe_y"))])

    def tool_probe(self, reference):
        # [BIESSE] TOOL_SENSOR = NO while no HAL pin carries the sensor: G38.2 would
        # otherwise run the full probe travel into the sensor
        if (INFO.INI.find("BIESSE", "TOOL_SENSOR") or "YES").strip().upper() in ("NO", "0", "FALSE"):
            self.add_message(None, "error", "Tool probe disabled: the tool sensor has no input "
                             "([BIESSE] TOOL_SENSOR = NO in the INI).")
            return
        if not self.save_probe_config():
            return
        s = self.poll()
        if not self.can_park():
            self.add_message(None, None, "Tool probe: machine must be on, homed and idle.")
            return
        tool = s.tool_in_spindle
        if not reference and tool <= 0:
            self.add_message(None, None, "Tool probe: load a tool first (T# M6).")
            return
        if not reference and self.probe_ref is None:
            self.add_message(None, None, "Tool probe: measure the reference tool on CONFIG first.")
            return
        x, y = self.probe_value("cfg_probe_x"), self.probe_value("cfg_probe_y")
        if x == 0 and y == 0:
            self.add_message(None, None, "Tool probe: set the sensor X/Y on CONFIG first.")
            return
        safe = self.park_position()["Z"]
        retract = self.probe_value("cfg_probe_retract")
        self.add_message(None, None, "Measuring %s..." % ("reference tool" if reference else "tool %d" % tool))
        self.mdi([
            "G49",
            "G53 G0 Z%.3f" % safe,
            "G53 G0 X%.3f Y%.3f" % (x, y),
            "G53 G0 Z%.3f" % self.probe_value("cfg_probe_start_z"),
            "G91",
            "G38.2 Z-%.3f F%.1f" % (self.probe_value("cfg_probe_max"), self.probe_value("cfg_probe_fast")),
            self.probe_check,
            "G0 Z%.3f" % retract,
            "G38.2 Z-%.3f F%.1f" % (retract * 2, self.probe_value("cfg_probe_slow")),
            self.probe_check,
            "G90",
        ], lambda: self.probe_done(reference, tool, safe))

    def probe_check(self):
        if self.poll().probe_tripped:
            return True
        self.add_message(None, "error", "Tool probe: sensor not triggered - stopped.")
        self.mdi(["G90", "G53 G0 Z%.3f" % self.park_position()["Z"]])
        return False

    def probe_done(self, reference, tool, safe):
        trigger_z = self.poll().probed_position[2]
        if reference:
            self.probe_ref = trigger_z
            self.show_probe_ref()
            self.save_probe_config()
            self.add_message(None, None, "Reference tool measured: trigger Z %.4f" % trigger_z)
            self.mdi(["G53 G0 Z%.3f" % safe])
            return
        length = trigger_z - self.probe_ref
        self.add_message(None, None, "Tool %d length offset %.4f" % (tool, length))
        self.mdi(["G10 L1 P%d Z%.4f" % (tool, length), "G43", "G53 G0 Z%.3f" % safe],
                 self.load_tool_table)

    # ------------------------------------------------------------ park
    def park_position(self):
        # first joint of each axis from [KINS] coordinates=..., HOME from [JOINT_n]
        kins = INFO.INI.find("KINS", "KINEMATICS") or ""
        coords = "XYZ"
        for part in kins.split():
            if part.startswith("coordinates="):
                coords = part.split("=", 1)[1].upper()
        pos = {}
        for a in AXES:
            joint = coords.find(a)
            pos[a] = float(INFO.INI.find("JOINT_%d" % joint, "HOME") or 0) if joint >= 0 else 0.0
        return pos

    def park(self, when_done=None):
        p = self.park_position()
        self.mdi(["G53 G0 Z%.3f" % p["Z"], "G53 G0 X%.3f Y%.3f" % (p["X"], p["Y"])], when_done)

    def can_park(self):
        s = self.poll()
        return self.machine_ready() and s.interp_state == linuxcnc.INTERP_IDLE and self.all_homed()

    def park_clicked(self):
        if not self.can_park():
            self.add_message(None, None, "Cannot park: machine must be on, homed and idle.")
            return
        self.park()

    def finish_close(self):
        self.closing = True
        self.w.close()

    def is_parked(self):
        # within 10 mm of the park position (machine coordinates), e.g. PARK pressed and not moved since
        s = self.poll()
        p = self.park_position()
        return all(abs(s.actual_position[i] - p[a]) < 10 for i, a in enumerate(AXES))

    def close_requested(self):
        if self.closing or not self.can_park() or self.is_parked():
            return False
        p = self.park_position()
        box = QtWidgets.QMessageBox(self.w)
        box.setWindowTitle("Close LinuxCNC")
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setText("Park before closing?\n\nRetract Z, then rapid X/Y to the home position\n"
                    "(X %.1f, Y %.1f, Z %.1f).\nKeep clear of the gantry." % (p["X"], p["Y"], p["Z"]))
        park = box.addButton("Park and close", QtWidgets.QMessageBox.AcceptRole)
        plain = box.addButton("Close without parking", QtWidgets.QMessageBox.DestructiveRole)
        box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(park)
        box.exec_()
        if box.clickedButton() == plain:
            return False
        if box.clickedButton() != park:
            return True
        warn = QtWidgets.QMessageBox(self.w)
        warn.setWindowTitle("WARNING - MACHINE WILL MOVE")
        warn.setIcon(QtWidgets.QMessageBox.Warning)
        warn.setText("THE MACHINE WILL MOVE NOW.\n\n"
                     "Z rapids UP to %.1f, then X and Y rapid to X %.1f, Y %.1f.\n"
                     "Make sure the gantry path is clear and nobody is at the machine."
                     % (p["Z"], p["X"], p["Y"]))
        move = warn.addButton("Move and close", QtWidgets.QMessageBox.AcceptRole)
        no = warn.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
        warn.setDefaultButton(no)
        warn.exec_()
        if warn.clickedButton() == move:
            self.park(self.finish_close)
        return True

    # ------------------------------------------------------------ qtvcp
    def __getitem__(self, item):
        return getattr(self, item)

    def __setitem__(self, item, value):
        return setattr(self, item, value)


def get_handlers(halcomp, widgets, paths):
    return [HandlerClass(halcomp, widgets, paths)]
