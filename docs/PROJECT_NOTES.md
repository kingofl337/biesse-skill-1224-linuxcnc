# Biesse Skill 1224 – LinuxCNC retrofit: project notes

Hand-off notes for whoever (person or AI assistant) continues this work. Read this first.
State as of 2026-11-10.

## The machine

- **Biesse Skill 1224** CNC router (electrical schematic in the repo root: labelled SKILL 408, serial 09184).
- **Control PC:** Debian 13 with an RT kernel, **LinuxCNC 2.9.10 "nyx" build** (`2.9.10nyx59`).
  SSH: `cnc@192.168.113.28` (key auth from the Windows PC). The operator also works at its own
  keyboard and **1440×900** monitor.
- **Motion card:** Yurtaev **YMTL2P** PCI MECHATROLINK-II card (PCI 1313:0712), HAL driver `nyx`
  (`/usr/lib/linuxcnc/modules/nyx.so`, Jul 4 build). FPGA firmware **nyx_mtl2 v3.9.3** (flashed 2026-11-03).
- **Drives:** 4 × Yaskawa SGDV-1R9D11A + SGMGV-05DDW motors, MECHATROLINK-II at 10 Mbps / 32-byte
  (drive DIP S3 SW1+SW2 ON; Biesse ran 4 Mbps / 17-byte).

| Station | nyx servo | Joint | Axis | Notes |
|---|---|---|---|---|
| 0x41 | servo-00 | 0 | X1 | gantry master (schematic pp. 101–102) |
| 0x42 | servo-01 | 1 | X2 | gantry follower |
| 0x43 | servo-02 | 2 | Y | |
| 0x44 | servo-03 | 3 | Z | brake |

- Kinematics `trivkins coordinates=XXYZ`. Scale (mm per motor rev): X1/X2 −48.267, Y 48.267, Z −20.0.
- Keep `par/empty.par`: nyx must not overwrite the Biesse drive tuning stored in the drives.
- Drive overtravel inputs P-OT/N-OT are active (Pn50A 0x1881, Pn50B 0x8882). Their 24 V comes via relay
  O.18 (PE302) on the HSD BH rack.

## Repository layout

- `linuxcnc/biesse/` – **the real machine config** (mirrors `~/linuxcnc/configs/biesse/` on the CNC PC).
  - `biesse.ini` – AXIS screen. `biesse_ui.ini` – the new touch screen. **Both carry the same joint/homing
    settings; change both.**
  - `biesse.hal` (shared), `biesse_ui_postgui.hal`, `biesse-pgui.hal` (AXIS PyVCP panel).
  - `biesse_ui.pref` – screen preferences (`[SCREEN_OPTIONS] desktop_notify = False` keeps errors out of pop-ups).
  - `biesse_ui.sh` – launcher. Desktop icon "Biesse-Skill-1224" runs `biesse_ui.ini`; "Biesse (AXIS)" runs `biesse.ini`.
  - `qtvcp/screens/biesse_ui/` – the **generated** screen at 0.75 scale (.ui, .qss, handler, images).
  - `tools/` – read-only HAL loggers used for homing work (see below). Older shell watchers sit in the folder root.
- `linuxcnc/biesse_sim/` – simulator config (VM `cnc@192.168.40.125`, 1920×1080) **and the screen source**:
  `gen_biesse_ui.py`, `biesse_ui_handler.py`, `biesse_ui.qss`. `qtvcp/screens/biesse_uc/` is an older
  qtdragon-based attempt, superseded.
- `linuxcnc/nc_files/xy-warmup.ngc` – warm-up program (also on the CNC PC Desktop).
- `As Built/` – drive parameter backups (SigmaWin+).

## The biesse_ui screen

Look modelled on the user's Stepcraft/UCCNC screens (no Stepcraft or UCCNC names/logos): orange #f26a21
(user's CHAOS logo) on a dark green weave.

- **Pages:** RUN, TOOLPATH, OFFSETS, TOOLS, MESSAGES, CONFIG, DEBUG. Right column: MACHINE ON, CYCLE START,
  SINGLE LINE, FEED HOLD, CYCLE STOP, FULL SPEED, round RESET.
- **Build:** edit `linuxcnc/biesse_sim/gen_biesse_ui.py` / `biesse_ui_handler.py` / `biesse_ui.qss`, then
  - sim (1920×1080): `python gen_biesse_ui.py qtvcp/screens/biesse_ui/biesse_ui.ui`
  - machine (1440×900): `python gen_biesse_ui.py ../biesse/qtvcp/screens/biesse_ui/biesse_ui.ui 0.75`
    (also writes the scaled .qss next to the .ui). Copy the handler into both screen folders.
  - `[DISPLAY] BIESSE_UI_SCALE` must match the generated scale. **Do not use `QT_SCALE_FACTOR`** – fractional
    Qt scaling broke painting ("QPainter not active"). A 1080p monitor is planned: regenerate at scale 1.
- **Features:** automatic mode switching (no MDI/jog/auto buttons); one-line message bar + MESSAGES page
  (ALARMS / MESSAGES with SAVE to `~/linuxcnc/logs` and CLEAR); errors never pop up except the Not-homed
  reminder; tool-in-spindle prompt at machine-on (applied with M61 after homing if not yet homed);
  park-on-close prompt (skipped within 10 mm of park); CYCLE STOP force-enabled out of E-stop
  (qtvcp left it disabled); DRO units "mm"/"IN" follow G21/G20.
- **Jog:** on-screen pad + keyboard (arrows = X/Y, PgUp/PgDn = Z, Shift = fast). Keyboard jogging must be
  **armed** with the JOG button in the pad (or any on-screen jog button); it flashes red/green and disarms on
  a click outside the jog panel, any other key, focus loss/pointer leaving the window, or machine off.
- **Speed cap:** X/Y feeds, rapids and jogs capped at `[BIESSE] LOCKED_MAX_FEED` (10000 mm/min) via
  `maxvel` until FULL SPEED is unlocked with `[BIESSE] FULL_SPEED_PASSWORD`; relocks on E-stop/start-up.
- **CONFIG:** programs folder, default jog speed, **Override limits** (unhomes, then joint-jogs with X1+X2
  together at `OVERRIDE_JOG_MAX`; temporarily sets `ini.0/1.home_sequence` to +2 because LinuxCNC refuses
  unhomed jogging of synchronized joints, restored before HOME), tool length sensor settings.
- **Tool probe is blocked** (`[BIESSE] TOOL_SENSOR = NO`): see open items.
- **Test hooks** (handler 1 s tick): write a page index to `/tmp/biesse_ui_page`, or `method int-args` to
  `/tmp/biesse_ui_call`.

## Homing (final, 2026-11-03)

All axes home on their **home cam switch + motor index pulse**. No axis stalls on a stop any more.
Since firmware v3.9.3, `nyx.0.servo-MM.in-00/01/02` = drive **P-OT / N-OT / DEC** (IO_MON bits 0–2).

| Axis | Home switch | Search / latch / final (mm/s) | Index | HOME_OFFSET | HOME |
|---|---|---|---|---|---|
| Z | `servo-03.in-02`, TRUE above Z ≈ −21.0 | +20 / **+1 (up)** / 5 | 2.2 mm above the edge | −18.771 | 0 |
| Y | `servo-02.in-02`, TRUE below Y ≈ −1713.7 | −60 / +1 / 30 | 5.89 mm past the release | −1704.1 | −1724 |
| X1+X2 | shared cam on `servo-00.in-02`, TRUE above X ≈ −25.6 | +60 / −1 / 30 | X1's, 6.14 mm past the release | −35.36 | 0 |

- **Z latch must be upward.** A downward index search from the switch latched a *false* index 2.7 mm away
  (frame 15 mm off, Z stalled at the top). Possible nyx index/direction bug – report to the developer.
- **X2 follows X1:** X1's `index-enable` drives both joints (`net x-index`) and `[JOINT_1]
  HOME_INDEX_NO_ENCODER_RESET = YES`. Without that setting LinuxCNC assumes X2's encoder reset at the index,
  gives X2 a wrong offset and the two motors fight.
- X/Y offsets were matched to the earlier tape-measured frame on the cam edges (±0.7 mm). Machine 0 is
  5 mm inside the + stop on X and Z; Y0 is at the Y+ end.
- Soft limits are 3 mm inside the physical stops: X −3359.6…2, Y −1728…2, Z −337.6…2. Stops measured:
  X− −3362.6, Y− ≈ −1731, Z− −340.676; + ends at +5.
- X/Y index homing with the *limit* switches was not viable (index within ~1 mm of the switch edges).

## Operating gotchas

- **Restarting LinuxCNC remotely:** `pkill -9 -f "^/usr/bin/python3 /usr/bin/qtvcp"`, wait for `milltask` to
  exit, `pkill -x wish8.6`, `rm -f /tmp/linuxcnc.lock`, then start `biesse_ui.sh` with
  `DISPLAY=:0 XAUTHORITY=~/.Xauthority` under `setsid nohup`. A plain pkill is ignored while a dialog is open.
- **Never `pkill -f` a pattern that also appears in your own ssh command line** – it kills the session.
- Restarting LinuxCNC means homing again. Closing LinuxCNC kills HAL user components (loggers die with SIGINT).
- `biesse.pos` restores joint positions at start-up. X1 and X2 must agree in it, or entering coordinated
  mode (e.g. the first MDI) makes X2 jump → following error. Edit it only with LinuxCNC stopped.
- Live `ini.N.*` HAL pins exist (limits, home_offset, home_sequence…); latch velocity / use-index do not.
- `xdotool` is not installed on the CNC PC. Screenshots: `python3 ~/shot.py out.png` (PyQt5 grabWindow).

## Tools (`linuxcnc/biesse/tools/`, copy to the config folder on the CNC PC to use)

- `home_log.py SECONDS J:S [J:S ...]` – logs joint J / nyx servo S every 20 ms when anything changes:
  positions, home state, home switch, index-enable, f-error, in-00..02, z-passed, torque-clamped, counts.
  Run it in a normal ssh session (not detached). Example: `python3 home_log.py 300 0:0 1:1 2:2 3:3 > /tmp/h.log`.
- `nyx_watch.py SECONDS` – logs changes of the nyx input/monitor pins on all four drives.
- `z-passed` changes during homing are **not** reliable index locations.

## Open items

1. **Tool length sensor has no HAL input** since firmware v3.9.3 (it was EXT1). TOOL PROBE is blocked by
   `TOOL_SENSOR = NO`; `motion.probe-input` is unconnected. Ask the nyx developer to add EXT1 back as a pin (or
   expose the full IO_MON word). Then: connect it in `biesse_ui_postgui.hal`, test polarity, set probe X/Y on
   CONFIG, measure the reference tool.
2. Report the downward-index false latch (Z) to the nyx developer.
3. **Gantry squaring (phase 2):** indicate both ends of the table, give X2 its own index
   (`servo-01.index-enable`) and a calibrated `[JOINT_1] HOME_OFFSET`. Inspect the gantry/bearings after the
   brief X1/X2 fight during testing (rack measured ~0.06 mm).
4. Re-touch any saved work offsets before precise work (X/Y frame moved up to ~±0.7 mm on 2026-11-03).
5. Tuning: raise acceleration (X/Y 375, Z 250 mm/s²), try feedforward (Pn109), check following error at
   full speed (`ferr-record.sh`).
6. Not wired yet: E-stop input, machine I/O rack (EtherCAT BH660 head; BH670 was the old M-II master),
   spindle/VFD (cap 18000 rpm, no reverse).
7. Sim VM config is behind: it has the screen but none of the 2026-11-03 homing changes.
8. The user wants their Stepcraft UCCNC screenset updated to match this screen at some point.
9. Older comment lines near the top of `biesse.hal` (commented-out limit/home nets) predate the firmware pin
   remap.

## Working agreements with the user

- Ask before anything that talks to the drives or moves the machine; the user is at the machine and
  presses HOME / RESET. Keep clear of the gantry warnings in every motion test.
- For homing changes: test with a safe final position (e.g. HOME far from the stops) and a 20 ms log, then
  set the real offsets.
- Deliverables for CAD go as STEP, never STL (user's global preference).
