#!/usr/bin/env zsh
# analyze_flows_sheets.zsh
# From a SFDC project, outputs active flow operations as TSV, ready to paste into Google Sheets.

FLOWS_DIR="${0:A:h}/../force-app/main/default/flows"

python3 - "$FLOWS_DIR" <<'PYTHON'
import sys
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

NS = "http://soap.sforce.com/2006/04/metadata"

def tag(name):
    return f"{{{NS}}}{name}"

def get_text(el, child):
    node = el.find(tag(child))
    return node.text.strip() if node is not None and node.text else None

# Map processType + triggerType -> human-readable flow type
def flow_type_label(process_type, trigger_type):
    if process_type == "Flow":
        return "Screen Flow"
    if process_type == "Workflow":
        return "Workflow"
    if process_type == "AutoLaunchedFlow":
        if trigger_type == "RecordBeforeSave":
            return "Record-Triggered (Before Save)"
        if trigger_type == "RecordAfterSave":
            return "Record-Triggered (After Save)"
        if trigger_type == "Scheduled":
            return "Scheduled"
        if trigger_type == "PlatformEvent":
            return "Platform Event"
        return "Autolaunched"
    return process_type or "Unknown"

# Map actionType -> human-readable operation label
ACTION_TYPE_LABELS = {
    "emailAlert":               "Email Alert",
    "emailSimple":              "Send Email",
    "slackPostMessage":         "Slack: Post Message",
    "slackCreateChannel":       "Slack: Create Channel",
    "slackInviteUsersToChannel":"Slack: Invite Users to Channel",
    "chatterPost":              "Chatter Post",
    "submit":                   "Approval Submit",
    "externalService":          "External Service Callout",
    "component":                None,   # UI-only (showToast etc.) — skip
    "flow":                     None,   # Subflow — skip
}

def parse_flow(path):
    tree = ET.parse(path)
    root = tree.getroot()

    if get_text(root, "status") != "Active":
        return None

    label       = get_text(root, "label") or os.path.basename(path)
    description = " ".join((get_text(root, "description") or "").split())
    process_type = get_text(root, "processType") or ""

    start_el      = root.find(tag("start"))
    trigger_type   = get_text(start_el, "triggerType") if start_el is not None else None
    trigger_object = get_text(start_el, "object")      if start_el is not None else None

    ftype = flow_type_label(process_type, trigger_type)

    # --- Record operations: object -> {op_type: set(fields)} ---
    ops = defaultdict(lambda: {"Queried": set(), "Updated": set(), "Created": set()})

    for lookup in root.findall(tag("recordLookups")):
        obj = get_text(lookup, "object")
        if not obj:
            continue
        for qf in lookup.findall(tag("queriedFields")):
            if qf.text:
                ops[obj]["Queried"].add(qf.text.strip())
        for oa in lookup.findall(tag("outputAssignments")):
            f = get_text(oa, "field")
            if f:
                ops[obj]["Queried"].add(f)

    for update in root.findall(tag("recordUpdates")):
        obj = get_text(update, "object")
        if not obj:
            input_ref = get_text(update, "inputReference")
            if input_ref and "$Record" in input_ref and trigger_object:
                obj = trigger_object
        if not obj:
            continue
        for ia in update.findall(tag("inputAssignments")):
            f = get_text(ia, "field")
            if f:
                ops[obj]["Updated"].add(f)

    for create in root.findall(tag("recordCreates")):
        obj = get_text(create, "object")
        if not obj:
            continue
        for ia in create.findall(tag("inputAssignments")):
            f = get_text(ia, "field")
            if f:
                ops[obj]["Created"].add(f)

    # --- Action calls: op_label -> set(action names) ---
    actions = defaultdict(set)
    for action_el in root.findall(tag("actionCalls")):
        atype = get_text(action_el, "actionType")
        aname = get_text(action_el, "actionName") or atype or ""

        op_label = ACTION_TYPE_LABELS.get(atype)
        if op_label is None:
            # Explicit None = skip; missing key = Apex or unknown
            if atype in ACTION_TYPE_LABELS:
                continue
            # Apex actions: use actionName to detect Slack via apex
            if atype == "apex":
                if "slack" in aname.lower():
                    op_label = "Slack: Post Message (Apex)"
                elif "chatter" in aname.lower():
                    op_label = "Chatter Post (Apex)"
                else:
                    op_label = "Apex Action"
            else:
                op_label = f"Action: {atype}"
        actions[op_label].add(aname)

    return label, description, ftype, trigger_object, ops, actions

def main():
    flows_dir = sys.argv[1]
    if not os.path.isdir(flows_dir):
        print(f"ERROR: directory not found: {flows_dir}", file=sys.stderr)
        sys.exit(1)

    files = sorted(
        f for f in os.listdir(flows_dir) if f.endswith(".flow-meta.xml")
    )

    headers = ["Type", "Flow", "Trigger Object", "Flow Type", "Description", "Object", "Operation", "Fields"]
    print("\t".join(headers))

    for fname in files:
        result = parse_flow(os.path.join(flows_dir, fname))
        if result is None:
            continue

        label, description, ftype, trigger_object, ops, actions = result
        base = ["Flow", label, trigger_object or "", ftype, description]

        has_rows = False

        # Record operation rows
        for obj in sorted(ops):
            for op_type in ("Queried", "Updated", "Created"):
                fields = sorted(ops[obj][op_type])
                if fields:
                    print("\t".join(base + [obj, op_type, ", ".join(fields)]))
                    has_rows = True

        # Action rows (no object)
        for op_label in sorted(actions):
            names = sorted(actions[op_label])
            print("\t".join(base + ["", op_label, ", ".join(names)]))
            has_rows = True

        # Flow has no operations at all
        if not has_rows:
            print("\t".join(base + ["", "", ""]))

main()
PYTHON
