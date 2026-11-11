#!/usr/bin/env python3
# Biesse UC screen: rebuild the main page of the qtdragon_hd-based .ui into a
# Stepcraft/UCCNC-style layout: full-width page-button bar on top, then three
# columns: toolpath + G-code | DRO, jog, spindle, offsets | E-stop, inputs,
# program buttons. Existing widgets are moved, not recreated, so the qtdragon
# handler keeps working. Usage: restructure_ui.py in.ui out.ui

import sys
import xml.etree.ElementTree as ET

src, dst = sys.argv[1], sys.argv[2]
tree = ET.parse(src)
root = tree.getroot()
parent = {c: p for p in root.iter() for c in p}


def find(tag, name):
    for e in root.iter(tag):
        if e.get("name") == name:
            return e
    raise KeyError(name)


def take_item(child):
    # detach the <item> that wraps a widget/layout and return it
    item = parent[child]
    assert item.tag == "item", (child.get("name"), item.tag)
    parent[item].remove(item)
    for attr in ("row", "column", "rowspan", "colspan", "alignment"):
        item.attrib.pop(attr, None)
    return item


def new_box(cls, name, items, stretch=None, spacing=6):
    lay = ET.Element("layout", {"class": cls, "name": name})
    sp = ET.SubElement(lay, "property", {"name": "spacing"})
    ET.SubElement(sp, "number").text = str(spacing)
    if stretch:
        # Qt Designer stores box stretch factors as an attribute of <layout>
        lay.set("stretch", ",".join(str(s) for s in stretch))
    for it in items:
        lay.append(it)
    return lay


def wrap(layout):
    item = ET.Element("item")
    item.append(layout)
    return item


def set_max_width(widget, width):
    prop = widget.find("property[@name='maximumSize']")
    if prop is not None:
        prop.find("size").find("width").text = str(width)


def set_hpolicy(widget, policy):
    prop = widget.find("property[@name='sizePolicy']")
    if prop is not None:
        prop.find("sizepolicy").set("hsizetype", policy)


main = find("layout", "verticalLayout_43")
upper = find("layout", "layout_upper")
lower = find("layout", "layout_lower")

buttonbar = take_item(find("widget", "frame_buttonbar"))
backplot = take_item(find("widget", "frm_backplot"))
gcode_w = find("widget", "frame_top_left")
set_max_width(gcode_w, 16777215)
set_hpolicy(gcode_w, "Expanding")
gcode = take_item(gcode_w)
dro = take_item(find("widget", "stackedWidget_dro"))
jog = take_item(find("widget", "frame_jogging"))
spindle = take_item(find("widget", "widget_spindle"))
offsets = take_item(find("widget", "widget_offsets_2"))
tool = take_item(find("widget", "frame_tool"))
program = take_item(find("widget", "frame_program"))
power = take_item(find("widget", "groupBox_power"))
inputs = take_item(find("widget", "groupBox_inputs"))
mode = take_item(find("widget", "groupBox_mode"))

# remove the old two-row structure
for old in (upper, lower):
    item = parent[old]
    parent[item].remove(item)

left = new_box("QVBoxLayout", "biesse_col_left", [backplot, gcode], stretch=[3, 2])
center_row = new_box("QHBoxLayout", "biesse_center_row", [jog, spindle, offsets])
center = new_box("QVBoxLayout", "biesse_col_center", [dro, wrap(center_row)], stretch=[0, 0])
right = new_box("QVBoxLayout", "biesse_col_right", [power, inputs, program], stretch=[0, 0, 1])
columns = new_box("QHBoxLayout", "biesse_columns",
                  [wrap(left), wrap(center), wrap(right)], stretch=[1, 0, 0])

# hidden on the main page (handled by biesse_customize): keep them in the tree
# so the qtdragon handler still finds them
parking = new_box("QHBoxLayout", "biesse_hidden", [tool, mode])

main.insert(0, buttonbar)
main.insert(1, wrap(columns))
main.insert(2, wrap(parking))
tree.write(dst, encoding="UTF-8", xml_declaration=True)
print("restructured ->", dst)
