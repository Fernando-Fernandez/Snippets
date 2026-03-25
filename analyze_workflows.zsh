#!/usr/bin/env zsh
# analyze_workflows.zsh
# Lists ACTIVE workflow rules (criteria, field updates, email alerts, tasks, outbound messages)
# Output is TSV ready to paste into Google Sheets.
# Columns: Type | Name | Trigger Object | Trigger Events/Type/Element | Source/Description | Detail/Object | Operation | Fields

WORKFLOWS_DIR="${0:A:h}/../force-app/main/default/workflows"

python3 - "$WORKFLOWS_DIR" <<'PYTHON'
import sys, os
import xml.etree.ElementTree as ET

NS = "http://soap.sforce.com/2006/04/metadata"

def tag(name):
    return f"{{{NS}}}{name}"

def get_text(el, child):
    node = el.find(tag(child))
    return " ".join(node.text.split()) if node is not None and node.text else ""

def get_all_text(el, child):
    return [" ".join(n.text.split()) for n in el.findall(tag(child)) if n.text]

def clean(s):
    return " ".join(s.split())

def format_recipients(alert_el):
    by_type = {}
    lookup_fields = []
    for r in alert_el.findall(tag("recipients")):
        rtype     = get_text(r, "type")
        recipient = get_text(r, "recipient")
        field     = get_text(r, "field")
        if field:
            lookup_fields.append(field)
        label = recipient or rtype
        by_type.setdefault(rtype, []).append(label)

    parts = []
    for rtype, values in by_type.items():
        unique = sorted(set(values))
        if rtype == "owner":
            parts.append("owner")
        elif rtype == "role":
            parts.append("role: " + ", ".join(unique))
        elif rtype == "userLookup":
            parts.append("userLookup: " + ", ".join(unique))
        else:
            parts.append(", ".join(unique))

    cc = get_all_text(alert_el, "ccEmails")
    if cc:
        parts.append("cc: " + ", ".join(cc))

    return "; ".join(parts), ", ".join(lookup_fields)

TRIGGER_TYPE_LABELS = {
    "onCreateOnly":       "On Create Only",
    "onAllChanges":       "On Create & Every Edit",
    "onCreateOrTriggeringUpdate": "On Create or Triggering Update",
}

def main():
    wf_dir = sys.argv[1]
    if not os.path.isdir(wf_dir):
        print(f"ERROR: directory not found: {wf_dir}", file=sys.stderr)
        sys.exit(1)

    headers = [
        "Type", "Name", "Trigger Object",
        "Trigger Events/Type/Element", "Source/Description",
        "Detail/Object", "Operation", "Fields"
    ]
    print("\t".join(headers))

    for fname in sorted(os.listdir(wf_dir)):
        if not fname.endswith(".workflow-meta.xml"):
            continue

        sobject = fname.replace(".workflow-meta.xml", "")
        tree    = ET.parse(os.path.join(wf_dir, fname))
        root    = tree.getroot()

        # Index alert/fieldUpdate/task definitions by fullName for lookup
        alerts       = {get_text(a, "fullName"): a for a in root.findall(tag("alerts"))}
        field_updates = {get_text(f, "fullName"): f for f in root.findall(tag("fieldUpdates"))}
        tasks        = {get_text(t, "fullName"): t for t in root.findall(tag("tasks"))}
        out_msgs     = {get_text(o, "fullName"): o for o in root.findall(tag("outboundMessages"))}

        # ── Active Workflow Rules ──────────────────────────────────
        active_alert_names = set()
        active_fu_names    = set()

        for rule in root.findall(tag("rules")):
            if get_text(rule, "active").lower() != "true":
                continue

            rname        = get_text(rule, "fullName")
            rdesc        = clean(get_text(rule, "description"))
            trigger_type = get_text(rule, "triggerType")
            trigger_label = TRIGGER_TYPE_LABELS.get(trigger_type, trigger_type)
            formula       = get_text(rule, "formula")
            filter_logic  = get_text(rule, "booleanFilter")

            # base: Type | Name | Trigger Object | Element | Description
            base = ["Workflow", rname, sobject, "Workflow Rule", rdesc]

            # Trigger type row
            print("\t".join(base + ["", "Trigger Type", trigger_label]))

            # Criteria
            if formula:
                print("\t".join(base + ["", "Criteria Formula", formula]))
            else:
                criteria = [
                    (get_text(ci, "field"), get_text(ci, "operation"), get_text(ci, "value"))
                    for ci in rule.findall(tag("criteriaItems"))
                ]
                if filter_logic:
                    print("\t".join(base + ["", "Criteria Filter Logic", filter_logic]))
                for field, operator, value in criteria:
                    print("\t".join(base + ["", "Criteria Field", f"{field} {operator} {value}".strip()]))

            # Immediate actions
            for action_ref in rule.findall(tag("actions")):
                atype = get_text(action_ref, "type")
                aname = get_text(action_ref, "name")
                if atype == "Alert":
                    active_alert_names.add(aname)
                elif atype == "FieldUpdate":
                    active_fu_names.add(aname)
                print("\t".join(base + ["", f"Action ({atype})", aname]))

            # Timed actions
            for trig in rule.findall(tag("workflowTimeTriggers")):
                offset = (get_text(trig, "offsetFromField")
                          or f"{get_text(trig, 'timeLength')} {get_text(trig, 'workflowTimeTriggerUnit')}")
                for action_ref in trig.findall(tag("actions")):
                    atype = get_text(action_ref, "type")
                    aname = get_text(action_ref, "name")
                    if atype == "Alert":
                        active_alert_names.add(aname)
                    elif atype == "FieldUpdate":
                        active_fu_names.add(aname)
                    print("\t".join(base + ["", f"Timed Action ({atype})", f"{aname} — offset: {offset}"]))

        # ── Email Alerts referenced by active rules ────────────────
        # If no rules exist in this file, show all alerts (they're referenced by flows)
        alert_scope = active_alert_names if active_alert_names else alerts.keys()

        for aname in sorted(alert_scope):
            alert = alerts.get(aname)
            if alert is None:
                continue
            adesc    = clean(get_text(alert, "description"))
            template = get_text(alert, "template")
            sender   = get_text(alert, "senderType")
            recipients_str, lookup_fields = format_recipients(alert)

            base = ["Workflow", aname, sobject, "Email Alert", adesc]
            print("\t".join(base + ["", "Template",    template]))
            print("\t".join(base + ["", "Sender Type", sender]))
            if recipients_str:
                print("\t".join(base + ["", "Recipients",  recipients_str]))
            if lookup_fields:
                print("\t".join(base + ["", "Recipient Lookup Field", lookup_fields]))

        # ── Field Updates referenced by active rules ───────────────
        for funame in sorted(active_fu_names):
            fu = field_updates.get(funame)
            if fu is None:
                continue
            fudesc = clean(get_text(fu, "description"))
            field  = get_text(fu, "field")
            value  = (get_text(fu, "formula")
                      or get_text(fu, "literalValue")
                      or get_text(fu, "lookupValue")
                      or get_text(fu, "newValue")
                      or ("[blank]" if get_text(fu, "notifyAssignee") else ""))
            re_eval = get_text(fu, "reevaluateOnChange")

            base = ["Workflow", funame, sobject, "Field Update", fudesc]
            print("\t".join(base + [sobject, "Updated Field", field]))
            if value:
                print("\t".join(base + [sobject, "New Value", value]))
            if re_eval:
                print("\t".join(base + [sobject, "Re-evaluate on Change", re_eval]))

        # ── Tasks referenced by active rules ──────────────────────
        active_task_names = set()
        for rule in root.findall(tag("rules")):
            if get_text(rule, "active").lower() != "true":
                continue
            for action_ref in rule.findall(tag("actions")):
                if get_text(action_ref, "type") == "Task":
                    active_task_names.add(get_text(action_ref, "name"))

        for tname in sorted(active_task_names):
            task = tasks.get(tname)
            if task is None:
                continue
            tdesc    = clean(get_text(task, "description"))
            subject  = get_text(task, "subject")
            assignee = get_text(task, "assignedToType")
            due_date = get_text(task, "dueDateOffset")
            priority = get_text(task, "priority")
            status   = get_text(task, "status")

            base = ["Workflow", tname, sobject, "Task", tdesc]
            print("\t".join(base + ["", "Subject",     subject]))
            print("\t".join(base + ["", "Assigned To", assignee]))
            if due_date:
                print("\t".join(base + ["", "Due Date Offset", due_date + " days"]))
            if priority:
                print("\t".join(base + ["", "Priority", priority]))
            if status:
                print("\t".join(base + ["", "Status", status]))

        # ── Outbound Messages referenced by active rules ───────────
        active_om_names = set()
        for rule in root.findall(tag("rules")):
            if get_text(rule, "active").lower() != "true":
                continue
            for action_ref in rule.findall(tag("actions")):
                if get_text(action_ref, "type") == "OutboundMessage":
                    active_om_names.add(get_text(action_ref, "name"))

        for omname in sorted(active_om_names):
            om = out_msgs.get(omname)
            if om is None:
                continue
            omdesc   = clean(get_text(om, "description"))
            endpoint = get_text(om, "endpointUrl")
            fields   = ", ".join(sorted(get_all_text(om, "fields")))

            base = ["Workflow", omname, sobject, "Outbound Message", omdesc]
            print("\t".join(base + ["", "Endpoint", endpoint]))
            if fields:
                print("\t".join(base + ["", "Fields Sent", fields]))

main()
PYTHON
