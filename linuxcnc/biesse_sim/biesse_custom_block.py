    #####################################################################
    # Biesse Skill 1224 customisation (UCCNC-style reskin of qtdragon_hd)
    #####################################################################

    # widgets this machine does not use
    # (frame_tool and groupBox_mode: off the main page in the three-column layout;
    #  tool data is on the TOOL page and QtDragon switches modes automatically)
    BIESSE_HIDE = ("btn_laser_on", "btn_ref_laser", "btn_ref_camera", "frame_modbus",
                   "btn_enable_comp", "widget_zaxis_offset", "frame_tool", "groupBox_mode")
    # UCCNC button names
    # (action_pause's PAUSE/RESUME labels are set in biesse_uc.ui)
    BIESSE_RENAME = {"action_abort": "CYCLE\nSTOP",
                     "action_step": "SINGLE\nLINE"}

    def biesse_customize(self):
        for name in self.BIESSE_HIDE:
            widget = getattr(self.w, name, None)
            if widget is not None:
                widget.hide()
        for name, text in self.BIESSE_RENAME.items():
            widget = getattr(self.w, name, None)
            if widget is not None:
                widget.setText(text)

        # big UCCNC-style RESET: E-stop reset + machine on, or back into E-stop
        self.biesse_reset = QtWidgets.QPushButton("RESET")
        self.biesse_reset.setObjectName("biesse_reset")
        self.biesse_reset.setMinimumHeight(56)
        self.biesse_reset.clicked.connect(self.biesse_reset_clicked)
        self.w.frame_program.layout().addWidget(self.biesse_reset)
        self.biesse_reset_state = None
        self.biesse_reset_timer = QtCore.QTimer()
        self.biesse_reset_timer.timeout.connect(lambda: self.biesse_reset_style(self.biesse_estopped()))
        self.biesse_reset_timer.start(500)
        self.biesse_reset_style(self.biesse_estopped())

        # reminder to home at machine-on
        STATUS.connect('state-on', lambda w: QtCore.QTimer.singleShot(300, self.biesse_home_reminder))

        # park on close
        self.biesse_closing = False
        self.biesse_close_filter = BiesseCloseFilter(self)
        self.w.installEventFilter(self.biesse_close_filter)

    def biesse_estopped(self):
        s = linuxcnc.stat()
        s.poll()
        return s.task_state == linuxcnc.STATE_ESTOP

    BIESSE_RESET_ESTOP = ("background: #d92d2d; color: #ffffff; border: 3px solid #ffffff;"
                          " font-size: 22pt; font-weight: bold;")
    BIESSE_RESET_READY = ("background: #5a1414; color: #ffb3b3; border: 2px solid #d92d2d;"
                          " font-size: 22pt; font-weight: bold;")

    def biesse_reset_style(self, estopped):
        # bright red while in E-stop (press to reset), dark red when running
        if estopped == self.biesse_reset_state:
            return
        self.biesse_reset_state = estopped
        self.biesse_reset.setStyleSheet(self.BIESSE_RESET_ESTOP if estopped else self.BIESSE_RESET_READY)

    def biesse_reset_clicked(self):
        if self.biesse_estopped():
            ACTION.SET_ESTOP_STATE(False)
            ACTION.SET_MACHINE_STATE(True)
        else:
            ACTION.SET_ESTOP_STATE(True)

    def biesse_all_homed(self):
        s = linuxcnc.stat()
        s.poll()
        return all(s.homed[j] for j in range(s.joints))

    def biesse_home_reminder(self):
        if self.biesse_all_homed():
            return
        QtWidgets.QMessageBox.warning(
            self.w, "Not homed",
            "Press HOME ALL before jogging. The axes MOVE to their limit switches:\n\n"
            "  Z  up to its + limit\n"
            "  Y  to its Y- limit\n"
            "  X  both gantry sides to their X+ limits\n\n"
            "Keep clear of the gantry.")

    # --- park ---------------------------------------------------------

    def biesse_park_position(self):
        # first joint of each axis from [KINS] coordinates=..., HOME from [JOINT_n]
        kins = INFO.INI.find("KINS", "KINEMATICS") or ""
        coords = "XYZ"
        for part in kins.split():
            if part.startswith("coordinates="):
                coords = part.split("=", 1)[1].upper()
        pos = {}
        for axis in "XYZ":
            joint = coords.find(axis)
            pos[axis] = float(INFO.INI.find("JOINT_%d" % joint, "HOME") or 0) if joint >= 0 else 0.0
        return pos

    def biesse_park_moves(self):
        p = self.biesse_park_position()
        return ["G53 G0 Z%.3f" % p["Z"], "G53 G0 X%.3f Y%.3f" % (p["X"], p["Y"])]

    def biesse_can_park(self):
        s = linuxcnc.stat()
        s.poll()
        return (not s.estop and s.task_state == linuxcnc.STATE_ON
                and s.interp_state == linuxcnc.INTERP_IDLE and self.biesse_all_homed())

    def biesse_park_step(self, moves, when_done):
        s = linuxcnc.stat()
        s.poll()
        if s.estop or s.task_state != linuxcnc.STATE_ON:
            QtWidgets.QMessageBox.critical(self.w, "Park aborted",
                                           "Machine was switched off or E-stopped during the park move.")
            return
        if s.interp_state != linuxcnc.INTERP_IDLE or not s.inpos:
            QtCore.QTimer.singleShot(100, lambda: self.biesse_park_step(moves, when_done))
            return
        if not moves:
            if when_done:
                when_done()
            return
        self.biesse_cmd.mdi(moves[0])
        QtCore.QTimer.singleShot(200, lambda: self.biesse_park_step(moves[1:], when_done))

    def biesse_park(self, when_done=None):
        self.biesse_cmd = linuxcnc.command()
        self.biesse_cmd.mode(linuxcnc.MODE_MDI)
        self.biesse_cmd.wait_complete()
        self.biesse_park_step(self.biesse_park_moves(), when_done)

    def biesse_finish_close(self):
        self.biesse_closing = True
        self.w.close()

    def biesse_close_requested(self):
        if self.biesse_closing:
            return False
        if not self.biesse_can_park():
            return False
        p = self.biesse_park_position()
        box = QtWidgets.QMessageBox(self.w)
        box.setWindowTitle("Close LinuxCNC")
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setText("Park before closing?\n\nRetract Z, then rapid X/Y to the home position\n"
                    "(X %.1f, Y %.1f, Z %.1f).\nKeep clear of the gantry." % (p["X"], p["Y"], p["Z"]))
        park = box.addButton("Park and close", QtWidgets.QMessageBox.AcceptRole)
        plain = box.addButton("Close without parking", QtWidgets.QMessageBox.DestructiveRole)
        cancel = box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
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
            self.biesse_park(self.biesse_finish_close)
        return True

