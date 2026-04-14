#!/usr/bin/env zsh
# analyze_listviews.zsh
# Lists all list views that have a <sharedTo> element, showing the sharing targets.
# Output is TSV ready to paste into Google Sheets.
# Columns: Type | Object | List View | Label | Filter Scope | Sharing Type | Shared With

OBJECTS_DIR="${0:A:h}/../force-app/main/default/objects"

python3 - "$OBJECTS_DIR" <<'PYTHON'
import sys, os
import xml.etree.ElementTree as ET

NS = "http://soap.sforce.com/2006/04/metadata"

def tag(name):
    return f"{{{NS}}}{name}"

def get_text(el, child):
    node = el.find(tag(child))
    return " ".join(node.text.split()) if node is not None and node.text else ""

# Human-readable labels for sharedTo child element names
SHARE_TYPE_LABELS = {
    "allInternalUsers":            "All Internal Users",
    "allCustomerPortalUsers":      "All Customer Portal Users",
    "group":                       "Public Group",
    "queue":                       "Queue",
    "role":                        "Role",
    "roleAndSubordinates":         "Role & Subordinates",
    "roleAndSubordinatesInternal": "Role & Internal Subordinates",
    "territory":                   "Territory",
    "territoryAndSubordinates":    "Territory & Subordinates",
}

def main():
    objects_dir = sys.argv[1]
    if not os.path.isdir(objects_dir):
        print(f"ERROR: directory not found: {objects_dir}", file=sys.stderr)
        sys.exit(1)

    print("\t".join(["Type", "Object", "List View", "Label", "Filter Scope", "Sharing Type", "Shared With"]))

    for obj_name in sorted(os.listdir(objects_dir)):
        lv_dir = os.path.join(objects_dir, obj_name, "listViews")
        if not os.path.isdir(lv_dir):
            continue

        for fname in sorted(os.listdir(lv_dir)):
            if not fname.endswith(".listView-meta.xml"):
                continue

            path = os.path.join(lv_dir, fname)
            tree = ET.parse(path)
            root = tree.getroot()

            shared_to = root.find(tag("sharedTo"))
            if shared_to is None:
                continue

            full_name    = get_text(root, "fullName")
            label        = get_text(root, "label")
            filter_scope = get_text(root, "filterScope")

            base = ["List View", obj_name, full_name, label, filter_scope]

            for child in shared_to:
                local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                share_type  = SHARE_TYPE_LABELS.get(local, local)
                shared_with = " ".join(child.text.split()) if child.text else ""
                print("\t".join(base + [share_type, shared_with]))

main()
PYTHON
