#!/usr/bin/env python3
# Biesse Skill 1224 - generate the QtVCP screen "biesse_ui" (.ui file).
# Layout follows the user's UCCNC/Stepcraft screens (Run, Toolpath, Offsets,
# Tools pages, persistent right-hand control column, orange left strip), built
# from standard QtVCP widgets. No third-party names or logos.
# Designed at 1920x1080. Usage: gen_biesse_ui.py out.ui [scale]
# scale (e.g. 0.75 for a 1440x900 monitor) shrinks every size, spacing and font;
# biesse_ui.qss is written next to out.ui, scaled the same way. Set the same value
# as [DISPLAY] BIESSE_UI_SCALE in the INI for the handler's own styles.
# (Qt's QT_SCALE_FACTOR=0.75 breaks painting on the machine, hence this.)

import os
import re
import sys
import xml.etree.ElementTree as ET

CUSTOM = {
    "ActionButton": ("IndicatedPushButton", "qtvcp.widgets.action_button"),
    "IndicatedPushButton": ("QPushButton", "qtvcp.widgets.simple_widgets"),
    "DROLabel": ("QLabel", "qtvcp.widgets.dro_widget"),
    "GCodeGraphics": ("QWidget", "qtvcp.widgets.gcode_graphics"),
    "GcodeDisplay": ("QWidget", "qtvcp.widgets.gcode_editor"),
    "MDILine": ("QLineEdit", "qtvcp.widgets.mdi_line"),
    "StatusLabel": ("QLabel", "qtvcp.widgets.status_label"),
    "ScreenOptions": ("QWidget", "qtvcp.widgets.screen_options"),
    "JogIncrements": ("QComboBox", "qtvcp.widgets.jog_increments"),
    "StatusSlider": ("QSlider", "qtvcp.widgets.status_slider"),
    "ToolOffsetView": ("QTableView", "qtvcp.widgets.tool_offsetview"),
}
used = set()


def prop(e, name, kind, value):
    p = ET.SubElement(e, "property", {"name": name})
    if name not in ("geometry", "windowTitle", "text", "minimumSize", "maximumSize",
                    "sizePolicy", "alignment", "checkable", "visible", "toolTip", "readOnly"):
        p.set("stdset", "0")
    if kind == "size":
        s = ET.SubElement(p, "size")
        ET.SubElement(s, "width").text = str(value[0])
        ET.SubElement(s, "height").text = str(value[1])
    elif kind == "bool":
        ET.SubElement(p, "bool").text = "true" if value else "false"
    elif kind == "policy":
        sp = ET.SubElement(p, "sizepolicy", {"hsizetype": value[0], "vsizetype": value[1]})
        ET.SubElement(sp, "horstretch").text = "0"
        ET.SubElement(sp, "verstretch").text = "0"
    elif kind == "set":
        ET.SubElement(p, "set").text = value
    elif kind == "color":
        c = ET.SubElement(p, "color")
        for k, v in zip(("red", "green", "blue"), value):
            ET.SubElement(c, k).text = str(v)
    else:
        ET.SubElement(p, kind).text = str(value)
    return p


def W(cls, name, text=None, mins=None, maxs=None, policy=None, checkable=None, **props):
    if cls in CUSTOM:
        used.add(cls)
    e = ET.Element("widget", {"class": cls, "name": name})
    if mins:
        prop(e, "minimumSize", "size", mins)
    if maxs:
        prop(e, "maximumSize", "size", maxs)
    if policy:
        prop(e, "sizePolicy", "policy", policy)
    if text is not None:
        prop(e, "text", "string", text)
    if checkable is not None:
        prop(e, "checkable", "bool", checkable)
    for k, v in props.items():
        if isinstance(v, bool):
            prop(e, k, "bool", v)
        elif isinstance(v, int):
            prop(e, k, "number", v)
        elif isinstance(v, float):
            prop(e, k, "double", v)
        else:
            prop(e, k, "string", v)
    return e


def L(cls, name, children, stretch=None, spacing=6, margins=0):
    lay = ET.Element("layout", {"class": cls, "name": name})
    if stretch:
        lay.set("stretch", ",".join(str(s) for s in stretch))
    sp = ET.SubElement(lay, "property", {"name": "spacing"})
    ET.SubElement(sp, "number").text = str(spacing)
    for side in ("leftMargin", "topMargin", "rightMargin", "bottomMargin"):
        m = ET.SubElement(lay, "property", {"name": side})
        ET.SubElement(m, "number").text = str(margins)
    for c in children:
        item = ET.SubElement(lay, "item")
        if isinstance(c, tuple):            # grid: (child, row, col[, rowspan, colspan])
            child = c[0]
            item.set("row", str(c[1]))
            item.set("column", str(c[2]))
            if len(c) > 3:
                item.set("rowspan", str(c[3]))
                item.set("colspan", str(c[4]))
        else:
            child = c
        if child == "stretch":
            sp = ET.SubElement(item, "spacer", {"name": "sp_%s_%d" % (name, len(lay))})
            o = ET.SubElement(sp, "property", {"name": "orientation"})
            ET.SubElement(o, "enum").text = "Qt::Vertical" if cls == "QVBoxLayout" else "Qt::Horizontal"
            t = ET.SubElement(sp, "property", {"name": "sizeType"})
            ET.SubElement(t, "enum").text = "QSizePolicy::Expanding"
            h = ET.SubElement(sp, "property", {"name": "sizeHint", "stdset": "0"})
            hs = ET.SubElement(h, "size")
            ET.SubElement(hs, "width").text = "20"
            ET.SubElement(hs, "height").text = "20"
            continue
        item.append(child)
    return lay


def box(cls, name, layout, **kw):
    w = W(cls, name, **kw)
    w.append(layout)
    return w


def btn(name, text, cls="QPushButton", h=48, w=None, **props):
    maxs = (w, h) if w else (16777215, h)
    return W(cls, name, text, mins=(w or 0, h), maxs=maxs, **props)


def act(name, text, action, h=48, **props):
    props[action] = True
    return btn(name, text, cls="ActionButton", h=h, **props)


def lbl(name, text, **kw):
    return W("QLabel", name, text, **kw)


def status(name, statusprop, template="%s", h=40, **kw):
    kw[statusprop] = True
    return W("StatusLabel", name, None, mins=(0, h), maxs=(16777215, h),
             textTemplate=template, alt_textTemplate=template, **kw)


def dro(name, axis_index, ref, h=56, letter=""):
    prefix = letter + "   " if letter else ""
    return W("DROLabel", name, None, mins=(0, h), maxs=(16777215, h),
             Qjoint_number=axis_index, Qreference_type=ref,
             metric_template=prefix + "%10.4f mm", imperial_template=prefix + "%9.4f IN")


AXES = ("X", "Y", "Z")


# ---------------------------------------------------------------- Run page
def view_bar(suffix):
    items = [act("view_clear" + suffix, "CLEAR", "view_change_action", view_type_string="clear"),
             act("view_zin" + suffix, "+", "view_change_action", view_type_string="zoom-in"),
             act("view_zout" + suffix, "-", "view_change_action", view_type_string="zoom-out"),
             act("view_p" + suffix, "ISO", "view_change_action", view_type_string="p"),
             act("view_z" + suffix, "TOP", "view_change_action", view_type_string="z"),
             act("view_x" + suffix, "SIDE", "view_change_action", view_type_string="x"),
             act("view_y" + suffix, "FRONT", "view_change_action", view_type_string="y")]
    return items


def jbtn(name, text, **kw):
    return btn(name, text, h=80, w=80, **kw)


JOG_STEPS = (("cont", "CONT"), ("001", "0.01"), ("01", "0.1"), ("1", "1"), ("10", "10"))
jog_panel = box("QFrame", "frame_jog", L("QHBoxLayout", "lay_jog", [
    L("QGridLayout", "grid_jog", [
        (jbtn("jog_y_pos", "Y+"), 0, 1),
        (jbtn("jog_x_neg", "X-"), 1, 0),
        (jbtn("jog_x_pos", "X+"), 1, 2),
        (jbtn("jog_enable", "JOG", checkable=True), 1, 1),
        (jbtn("jog_y_neg", "Y-"), 2, 1),
        (jbtn("jog_z_pos", "Z+"), 0, 4),
        (jbtn("jog_z_neg", "Z-"), 2, 4),
    ], spacing=8),
    L("QVBoxLayout", "lay_jog_right", [
        lbl("lbl_jog_title", "JOG"),
        lbl("lbl_jog_step", "STEP (mm)"),
        L("QHBoxLayout", "lay_jog_steps",
          [btn("jog_step_" + k, t, h=48, w=64, checkable=True) for k, t in JOG_STEPS], spacing=4),
        L("QHBoxLayout", "lay_jog_speed_hdr", [
            lbl("lbl_jog_rate", "SPEED"), "stretch", lbl("lbl_jog_speed", "0 mm/min")]),
        W("QSlider", "jog_speed", None, mins=(0, 40)),
        "stretch",
    ], spacing=8),
], stretch=[0, 1], spacing=20, margins=10))

graphics = W("GCodeGraphics", "gcodegraphics", None, policy=("Expanding", "Expanding"),
             _dro=False, _dtg=False, _overlay=False, _offsets=True, _small_origin=True,
             _use_gradient_background=False)
prop(graphics, "background_color", "color", (0, 0, 0))
host_graphics = box("QWidget", "host_graphics_run",
                    L("QVBoxLayout", "lay_host_run", [graphics]), policy=("Expanding", "Expanding"))

run_left = L("QVBoxLayout", "lay_run_left", [
    L("QHBoxLayout", "lay_run_view", [
        box("QWidget", "viewbar_run", L("QVBoxLayout", "lay_viewbar_run", view_bar("") + ["stretch"]),
            mins=(80, 0), maxs=(80, 16777215)),
        host_graphics,
    ], stretch=[0, 1]),
    W("GcodeDisplay", "gcodedisplay", None, policy=("Expanding", "Expanding")),
], stretch=[3, 2])

dro_rows = []
for i, a in enumerate(AXES):
    dro_rows += [
        (btn("btn_zero_" + a.lower(), "ZERO", h=56, w=80), i, 2),
        (lbl("lbl_axis_" + a.lower(), a, mins=(44, 56), maxs=(44, 56)), i, 3),
        (dro("dro_work_" + a.lower(), i, 1), i, 4),
        (dro("dro_mach_" + a.lower(), i, 0), i, 5),
    ]
dro_grid = L("QGridLayout", "grid_dro", [
    (btn("btn_machine", "M\nA\nC\nH", h=180, w=48, checkable=True), 0, 0, 3, 1),
    (btn("btn_zero_all", "Z\nE\nR\nO", h=180, w=48), 0, 1, 3, 1),
] + dro_rows + [
    (btn("btn_home_all", "H\nO\nM\nE", h=180, w=48), 0, 6, 3, 1),
], spacing=6)

fs_grid = L("QGridLayout", "grid_fs", [
    (status("lbl_fset", "fcode_status", "Fset  %.1f"), 0, 0),
    (status("lbl_fact", "current_feedrate_status", "Fact  %.1f"), 0, 1),
    (btn("btn_feed_minus", "-", h=40, w=48), 0, 2),
    (status("lbl_feed_ovr", "feed_override_status", "%d%%"), 0, 3),
    (btn("btn_feed_plus", "+", h=40, w=48), 0, 4),
    (status("lbl_sset", "requested_spindle_speed_status", "Sset  %.0f"), 1, 0),
    (status("lbl_sact", "actual_spindle_speed_status", "Sact  %.0f"), 1, 1),
    (btn("btn_spindle_minus", "-", h=40, w=48), 1, 2),
    (status("lbl_spindle_ovr", "spindle_override_status", "%d%%"), 1, 3),
    (btn("btn_spindle_plus", "+", h=40, w=48), 1, 4),
], spacing=6)

act_grid = L("QGridLayout", "grid_actions", [
    (act("btn_spindle_cw", "SPINDLE CW", "spindle_fwd_action"), 0, 0),
    (act("btn_spindle_stop", "SPINDLE STOP", "spindle_stop_action"), 0, 1),
    (btn("btn_goto_zero", "GOTO ZERO"), 0, 2),
    (btn("btn_park", "PARK"), 0, 3),
] + [(btn("btn_g5%d" % (4 + i), "G5%d" % (4 + i), checkable=True), 1 + i // 3, i % 3)
     for i in range(6)] + [
    (btn("btn_safe_z", "SAFE Z"), 1, 3),
    (act("btn_run_from_here", "RUN FROM HERE", "run_from_status_action"), 2, 3),
], spacing=6)

file_row = L("QHBoxLayout", "lay_file", [
    btn("btn_load_file", "LOAD FILE"),
    btn("btn_reload_file", "REWIND FILE"),
    btn("btn_tool_probe", "TOOL PROBE"),
], spacing=6)

mdi_bar = box("QFrame", "frame_mdi", L("QGridLayout", "grid_mdi", [
    (lbl("lbl_mdi", "MDI", mins=(80, 44), maxs=(80, 44)), 0, 0),
    (W("MDILine", "mdiline", None, mins=(0, 44), maxs=(16777215, 44)), 0, 1),
    (status("lbl_gcodes", "gcodes_status", "ACTIVE: %s", h=30), 1, 0, 1, 2),
], spacing=4, margins=6))

# latest message on one line (tap for the MESSAGES page), then tool and run time
message_row = L("QHBoxLayout", "lay_run_message", [
    btn("btn_last_message", "", h=44, policy=("Ignored", "Fixed")),
    status("lbl_tool", "tool_number_status", "TOOL %d", h=44),
    lbl("lbl_runtime", "00:00:00", mins=(150, 44), maxs=(150, 44)),
    btn("btn_runtime_zero", "ZERO TIME", h=44, w=150),
], stretch=[4, 1, 0, 0], spacing=6)

run_center = L("QVBoxLayout", "lay_run_center",
               [dro_grid, fs_grid, act_grid, file_row, mdi_bar, message_row, jog_panel, "stretch"],
               stretch=[0, 0, 0, 0, 0, 0, 0, 1], spacing=8)

page_run = box("QWidget", "page_run", L("QHBoxLayout", "lay_page_run", [run_left, run_center],
                                        stretch=[4, 5], spacing=10))

# ----------------------------------------------------------- Toolpath page
tp_dro = L("QHBoxLayout", "lay_tp_dro",
           [dro("dro_tp_" + a.lower(), i, 1, h=48, letter=a) for i, a in enumerate(AXES)], spacing=8)
tp_fs = L("QHBoxLayout", "lay_tp_fs", [
    status("lbl_tp_fset", "fcode_status", "Fset  %.1f"),
    status("lbl_tp_fact", "current_feedrate_status", "Fact  %.1f"),
    status("lbl_tp_feed_ovr", "feed_override_status", "%d%%"),
    status("lbl_tp_sset", "requested_spindle_speed_status", "Sset  %.0f"),
    status("lbl_tp_sact", "actual_spindle_speed_status", "Sact  %.0f"),
    status("lbl_tp_spindle_ovr", "spindle_override_status", "%d%%"),
], spacing=8)
page_toolpath = box("QWidget", "page_toolpath", L("QVBoxLayout", "lay_page_tp", [
    L("QHBoxLayout", "lay_tp_main", [
        box("QWidget", "viewbar_tp", L("QVBoxLayout", "lay_viewbar_tp", view_bar("_tp") + [
            btn("btn_tp_load", "LOAD\nFILE", h=60),
            btn("btn_tp_reload", "REWIND\nFILE", h=60),
            "stretch"]), mins=(90, 0), maxs=(90, 16777215)),
        box("QWidget", "host_graphics_tp", L("QVBoxLayout", "lay_host_tp", []),
            policy=("Expanding", "Expanding")),
    ], stretch=[0, 1]),
    tp_dro, tp_fs,
], stretch=[1, 0, 0], spacing=8))

# ------------------------------------------------------------ Offsets page
off_rows = [(lbl("hdr_" + n, t), 0, c) for n, t, c in (
    ("cur", "Current coords", 1), ("mach", "Machine coords", 3), ("work", "Work offset", 5),
    ("g92", "G92 offset", 7), ("tool", "Tool offset", 9))]
for i, a in enumerate(AXES):
    r = i + 1
    off_rows += [
        (lbl("off_axis_" + a.lower(), a), r, 0),
        (dro("off_cur_" + a.lower(), i, 1, h=48), r, 1),
        (lbl("off_eq_" + a.lower(), "="), r, 2),
        (dro("off_mach_" + a.lower(), i, 0, h=48), r, 3),
        (lbl("off_m1_" + a.lower(), "-"), r, 4),
        (lbl("off_work_" + a.lower(), "0.0000", mins=(0, 48)), r, 5),
        (lbl("off_m2_" + a.lower(), "-"), r, 6),
        (lbl("off_g92_" + a.lower(), "0.0000", mins=(0, 48)), r, 7),
    ]
off_rows += [(lbl("off_m3_z", "-"), 3, 8), (lbl("off_tool_z", "0.0000", mins=(0, 48)), 3, 9)]
page_offsets = box("QWidget", "page_offsets", L("QVBoxLayout", "lay_page_off", [
    L("QHBoxLayout", "lay_off_tabs",
      [btn("btn_off_g5%d" % (4 + i), "G5%d" % (4 + i), h=40, checkable=True) for i in range(6)],
      spacing=6),
    lbl("lbl_off_title", "Offset Table"),
    L("QGridLayout", "grid_offsets", off_rows, spacing=8),
    lbl("lbl_active_fixture", "Active fixture: G54"),
    L("QHBoxLayout", "lay_off_btns", [
        btn("btn_off_set_current", "OFFSET CURRENT\nPOSITION", h=56),
        btn("btn_off_clear_work", "CLEAR WORK\nOFFSET", h=56),
        btn("btn_off_clear_g92", "CLEAR G92\nOFFSET", h=56),
        btn("btn_off_clear_tool", "CLEAR TOOL\nOFFSET", h=56),
    ], spacing=12),
    "stretch",
], spacing=14, margins=20))

# --------------------------------------------------------------- Tools page
page_tools = box("QWidget", "page_tools", L("QVBoxLayout", "lay_page_tools", [
    lbl("lbl_tools_title", "Tool Table"),
    W("QTableWidget", "tool_table", None, policy=("Expanding", "Expanding")),
    L("QHBoxLayout", "lay_tools_btns", [
        btn("btn_tools_add", "ADD TOOL", h=56, w=220),
        btn("btn_tools_reload", "RELOAD", h=56, w=220),
        "stretch",
        btn("btn_tools_apply", "APPLY CHANGES", h=56, w=300),
    ], spacing=12),
], spacing=10, margins=20))

# ------------------------------------------------------------ Messages page
def log_section(key, title):
    return box("QFrame", "frame_" + key, L("QVBoxLayout", "lay_" + key, [
        lbl("hdr_" + key, title),
        W("QPlainTextEdit", key + "_log", None, readOnly=True, policy=("Expanding", "Expanding")),
        L("QHBoxLayout", "lay_%s_btns" % key, [
            "stretch",
            btn("btn_%s_save" % key, "SAVE", h=56, w=180),
            btn("btn_%s_clear" % key, "CLEAR", h=56, w=180),
        ], spacing=12),
    ], spacing=8, margins=10))


page_messages = box("QWidget", "page_messages", L("QVBoxLayout", "lay_page_messages", [
    lbl("lbl_messages_title", "Messages"),
    L("QHBoxLayout", "lay_messages_cols",
      [log_section("alarms", "ALARMS"), log_section("messages", "MESSAGES")], spacing=12),
], stretch=[0, 1], spacing=10, margins=20))

# --------------------------------------------------------------- Debug page
page_debug = box("QWidget", "page_debug", L("QVBoxLayout", "lay_page_debug", [
    lbl("lbl_debug_title", "HAL Pins"),
    W("QTableWidget", "debug_table", None, policy=("Expanding", "Expanding")),
    L("QHBoxLayout", "lay_debug_btns", [
        W("QLineEdit", "debug_pin_name", None, mins=(500, 48), maxs=(16777215, 48)),
        btn("btn_debug_add", "ADD PIN", h=48, w=180),
        btn("btn_debug_remove", "REMOVE SELECTED", h=48, w=260),
    ], spacing=12),
], spacing=10, margins=20))

# -------------------------------------------------------------- Config page
CFG_FIELDS = (
    ("cfg_probe_x", "Probe X (machine)", "X position of the tool length sensor"),
    ("cfg_probe_y", "Probe Y (machine)", "Y position of the tool length sensor"),
    ("cfg_probe_start_z", "Start Z (machine)", "rapid down to here before probing"),
    ("cfg_probe_max", "Max probe travel", "fails if the sensor is not hit within this"),
    ("cfg_probe_fast", "Fast probe feed", "mm/min, first touch"),
    ("cfg_probe_slow", "Slow probe feed", "mm/min, measuring touch"),
    ("cfg_probe_retract", "Retract", "mm back off between touches"),
)
cfg_rows = [(lbl("hdr_cfg_probe", "Tool length sensor"), 0, 0, 1, 3)]
for r, (name, text, hint) in enumerate(CFG_FIELDS, start=1):
    cfg_rows += [
        (lbl("lbl_" + name, text, mins=(260, 44)), r, 0),
        (W("QLineEdit", name, None, mins=(200, 44), maxs=(200, 44)), r, 1),
        (lbl("hint_" + name, hint), r, 2),
    ]
r = len(CFG_FIELDS) + 1
cfg_rows += [
    (lbl("lbl_cfg_ref", "Reference height", mins=(260, 44)), r, 0),
    (lbl("cfg_probe_ref", "not measured", mins=(200, 44), maxs=(200, 44)), r, 1),
    (lbl("hint_cfg_ref", "trigger Z of the reference tool; tool lengths are relative to it"), r, 2),
]
programs_row = L("QGridLayout", "grid_cfg_programs", [
    (lbl("hdr_cfg_programs", "Programs"), 0, 0, 1, 3),
    (lbl("lbl_cfg_program_dir", "Programs folder", mins=(260, 44)), 1, 0),
    (W("QLineEdit", "cfg_program_dir", None, mins=(0, 44), maxs=(16777215, 44)), 1, 1),
    (btn("btn_cfg_browse_dir", "BROWSE", h=44, w=180), 1, 2),
], spacing=10)

jog_row = L("QGridLayout", "grid_cfg_jog", [
    (lbl("hdr_cfg_jog", "Jog"), 0, 0, 1, 3),
    (lbl("lbl_cfg_jog_default", "Default jog speed", mins=(260, 44)), 1, 0),
    (W("QLineEdit", "cfg_jog_default", None, mins=(200, 44), maxs=(200, 44)), 1, 1),
    (lbl("hint_cfg_jog_default", "mm/min, jog speed slider at start-up; hold Shift to jog fast (arrow keys, PgUp/PgDn = Z)"), 1, 2),
    (W("QCheckBox", "cfg_override_limits", "Override limits (jog without homing)", mins=(0, 44)), 2, 0, 1, 2),
    (lbl("hint_cfg_override_limits", "unhomes the machine; slow jog with no soft limits, X moves both gantry sides; off at E-stop or after HOME"), 2, 2),
], spacing=10)

page_config = box("QWidget", "page_config", L("QVBoxLayout", "lay_page_cfg", [
    lbl("lbl_cfg_title", "Configuration"),
    programs_row,
    jog_row,
    L("QGridLayout", "grid_cfg", cfg_rows, spacing=10),
    L("QHBoxLayout", "lay_cfg_btns", [
        btn("btn_cfg_teach_xy", "USE CURRENT\nX/Y", h=60),
        btn("btn_cfg_goto_probe", "GO TO\nPROBE", h=60),
        btn("btn_cfg_set_ref", "MEASURE\nREFERENCE TOOL", h=60),
        btn("btn_cfg_save", "SAVE\nSETTINGS", h=60),
    ], spacing=12),
    "stretch",
], spacing=16, margins=20))

# ------------------------------------------------------------- right column
right = box("QFrame", "frame_right", L("QVBoxLayout", "lay_right", [
    lbl("lbl_brand", "BIESSE\nSKILL 1224", mins=(0, 90)),
    act("btn_machine_on", "MACHINE\nON", "machine_on_action", h=90),
    act("btn_cycle_start", "CYCLE\nSTART", "run_action", h=110),
    act("btn_single_line", "SINGLE\nLINE", "step_action", h=110),
    act("btn_feed_hold", "FEED\nHOLD", "pause_action", h=110, checkable=True,
        checked_state_text_option=True, true_state_string="RESUME",
        false_state_string="FEED\nHOLD"),
    act("btn_cycle_stop", "CYCLE\nSTOP", "abort_action", h=110),
    btn("btn_full_speed", "FULL\nSPEED", h=80),
    "stretch",
    btn("btn_reset", "RESET", h=180, w=180),
    W("ScreenOptions", "screen_options", None, maxs=(1, 1),
      notify_option=False, catch_errors_option=True, catch_close_option=False,
      fileDialog_option=True, messageDialog_option=True, entryDialog_option=True,
      closeDialog_option=False, toolDialog_option=False, use_pref_file_option=True),
], spacing=10, margins=10), mins=(220, 0), maxs=(220, 16777215))

# ---------------------------------------------------------------- top level
tabs = box("QFrame", "frame_tabs", L("QHBoxLayout", "lay_tabs", [
    btn("btn_page_run", "RUN", h=44, w=150, checkable=True),
    btn("btn_page_toolpath", "TOOLPATH", h=44, w=200, checkable=True),
    btn("btn_page_offsets", "OFFSETS", h=44, w=180, checkable=True),
    btn("btn_page_tools", "TOOLS", h=44, w=150, checkable=True),
    btn("btn_page_messages", "MESSAGES", h=44, w=220, checkable=True),
    btn("btn_page_config", "CONFIG", h=44, w=160, checkable=True),
    btn("btn_page_debug", "DEBUG", h=44, w=150, checkable=True),
    "stretch",
    act("btn_exit", "EXIT", "exit_action", h=44, w=140),
], spacing=8, margins=6))

stack = ET.Element("widget", {"class": "QStackedWidget", "name": "stack_pages"})
for page in (page_run, page_toolpath, page_offsets, page_tools, page_messages, page_config,
             page_debug):
    stack.append(page)

strip = box("QFrame", "frame_strip", L("QVBoxLayout", "lay_strip", ["stretch"], margins=0),
            mins=(36, 0), maxs=(36, 16777215))

central = box("QWidget", "centralwidget", L("QHBoxLayout", "lay_central", [
    strip,
    L("QVBoxLayout", "lay_main", [tabs, stack], stretch=[0, 1], spacing=8),
    right,
], stretch=[0, 1, 0], spacing=8, margins=4))

ui = ET.Element("ui", {"version": "4.0"})
ET.SubElement(ui, "class").text = "MainWindow"
mw = ET.SubElement(ui, "widget", {"class": "QMainWindow", "name": "MainWindow"})
g = ET.SubElement(mw, "property", {"name": "geometry"})
r = ET.SubElement(g, "rect")
for k, v in (("x", 0), ("y", 0), ("width", 1920), ("height", 1080)):
    ET.SubElement(r, k).text = str(v)
prop(mw, "windowTitle", "string", "Biesse Skill 1224")
mw.append(central)

cws = ET.SubElement(ui, "customwidgets")
for cls in sorted(used | {"IndicatedPushButton"}):
    c = ET.SubElement(cws, "customwidget")
    ET.SubElement(c, "class").text = cls
    ET.SubElement(c, "extends").text = CUSTOM[cls][0]
    ET.SubElement(c, "header").text = CUSTOM[cls][1]
ET.SubElement(ui, "resources")
ET.SubElement(ui, "connections")

# ------------------------------------------------------------------ scaling
SCALE = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0


def sc(v):
    return max(1, round(v * SCALE)) if v else 0


if SCALE != 1.0:
    for e in ui.iter():
        if e.tag in ("size", "rect"):
            for k in e:
                if k.tag in ("width", "height") and int(k.text) != 16777215:
                    k.text = str(sc(int(k.text)))
        elif e.tag == "property" and e.get("name") in (
                "spacing", "leftMargin", "topMargin", "rightMargin", "bottomMargin"):
            n = e.find("number")
            n.text = str(sc(int(n.text)))

ET.indent(ui)
ET.ElementTree(ui).write(sys.argv[1], encoding="UTF-8", xml_declaration=True)
print("wrote", sys.argv[1], "scale", SCALE)

# stylesheet: px and pt values, and the point size inside qproperty font strings
qss = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "biesse_ui.qss"),
           encoding="utf-8").read()
qss = re.sub(r"(-?)(\d+)(px|pt)", lambda m: "%s%d%s" % (m.group(1), sc(int(m.group(2))), m.group(3)), qss)
qss = re.sub(r'(qproperty-styleFont\d?: "[^,]+,)(\d+)', lambda m: m.group(1) + str(sc(int(m.group(2)))), qss)
out = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "biesse_ui.qss")
open(out, "w", encoding="utf-8", newline="\n").write(qss)
print("wrote", out)
