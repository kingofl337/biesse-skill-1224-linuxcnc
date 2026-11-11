#!/bin/sh
# Start LinuxCNC with the Biesse touch screen.
cd "$(dirname "$0")" && exec linuxcnc biesse_ui.ini
