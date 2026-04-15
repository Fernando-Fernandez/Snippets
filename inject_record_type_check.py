#!/usr/bin/env python3
"""
Inject a Check_Record_Type decision gate into a Salesforce Flow XML.

Supports two flow formats:
  - Modern: <start><connector><targetReference>X</targetReference>...
  - Legacy: <startElementReference>X</startElementReference>

Actions:
- Reads the start reference (modern or legacy) and saves it
- Replaces it with "Check_Record_Type"
- Inserts a <decisions> block that routes SDC_Lead records to a dedicated
  path and all others to the original target via the default connector
- Ensures <status>Active</status>
- Deploys and activates via `sf project deploy start`

Usage:
    python3 scripts/inject_record_type_check.py <path-to-flow-meta.xml>
"""

import os
import re
import shutil
import subprocess
import sys


# ── helpers ─────────────────────────────────────────────────────────────────

def abort(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def find_project_root(start: str) -> str:
    """Walk up from `start` until sfdx-project.json is found."""
    current = os.path.abspath(start)
    for _ in range(10):
        if os.path.isfile(os.path.join(current, "sfdx-project.json")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    abort(
        "Could not find sfdx-project.json. "
        "Run this script from inside a Salesforce project."
    )


def decisions_block(original_target: str) -> str:
    return (
        "    <decisions>\n"
        "        <name>Check_Record_Type</name>\n"
        "        <label>Check Record Type</label>\n"
        "        <locationX>0</locationX>\n"
        "        <locationY>0</locationY>\n"
        "        <defaultConnector>\n"
        f"            <targetReference>{original_target}</targetReference>\n"
        "        </defaultConnector>\n"
        "        <defaultConnectorLabel>Default Outcome</defaultConnectorLabel>\n"
        "        <rules>\n"
        "            <name>SDC_Record_Type</name>\n"
        "            <conditionLogic>and</conditionLogic>\n"
        "            <conditions>\n"
        "                <leftValueReference>$Record.RecordType.DeveloperName</leftValueReference>\n"
        "                <operator>EqualTo</operator>\n"
        "                <rightValue>\n"
        "                    <stringValue>SDC_Lead</stringValue>\n"
        "                </rightValue>\n"
        "            </conditions>\n"
        "            <label>SDC Record Type</label>\n"
        "        </rules>\n"
        "    </decisions>\n"
    )


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    flow_path = os.path.abspath(sys.argv[1])

    if not os.path.isfile(flow_path):
        abort(f"File not found: {flow_path}")

    project_root = find_project_root(os.path.dirname(flow_path))
    print(f"Project root : {project_root}")
    print(f"Flow file    : {flow_path}")

    # ── read ──────────────────────────────────────────────────────────────
    with open(flow_path, "r", encoding="utf-8") as fh:
        content = fh.read()

    # ── check flow status ─────────────────────────────────────────────────
    status_match = re.search(r"<status>([^<]+)</status>", content)
    if status_match:
        flow_status = status_match.group(1).strip()
        print(f"Flow status  : {flow_status}")
        if flow_status == "Obsolete":
            abort("Flow status is Obsolete. This flow cannot be modified or deployed.")
    else:
        print("Flow status  : (not set)")

    # ── locate start reference ────────────────────────────────────────────
    #
    # Two formats exist in Salesforce flow XML:
    #   1. Modern:  <start>...<connector><targetReference>X</targetReference>...
    #   2. Legacy:  <startElementReference>X</startElementReference>
    #
    start_match = re.search(r"(<start>.*?</start>)", content, re.DOTALL)

    if start_match:
        start_block = start_match.group(1)
        ref_match = re.search(
            r"<connector>\s*<targetReference>([^<]+)</targetReference>\s*</connector>",
            start_block,
        )
        if not ref_match:
            abort("Found <start> element but could not find <connector><targetReference> inside it.")

        original_target = ref_match.group(1).strip()
        start_format = "modern"
        print(f"Format               : modern (<start><connector><targetReference>)")
    else:
        # Fall back to legacy <startElementReference>
        ref_match = re.search(r"<startElementReference>([^<]+)</startElementReference>", content)
        if not ref_match:
            abort(
                "Could not find a start reference. "
                "Expected either <start><connector><targetReference> or <startElementReference>."
            )
        original_target = ref_match.group(1).strip()
        start_format = "legacy"
        print(f"Format               : legacy (<startElementReference>)")

    print(f"Original targetReference: {original_target}")

    if original_target == "Check_Record_Type":
        print("targetReference is already 'Check_Record_Type' — nothing to do.")
        sys.exit(0)

    # ── backup (stored outside force-app to avoid deploy conflicts) ──────
    script_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(script_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, os.path.basename(flow_path) + ".bak")
    shutil.copy2(flow_path, backup_path)
    print(f"Backup created : {backup_path}")

    # ── patch the start reference ─────────────────────────────────────────
    if start_format == "modern":
        new_start_block = start_block.replace(
            f"<targetReference>{original_target}</targetReference>",
            "<targetReference>Check_Record_Type</targetReference>",
            1,
        )
        content = content.replace(start_block, new_start_block, 1)
    else:
        content = content.replace(
            f"<startElementReference>{original_target}</startElementReference>",
            "<startElementReference>Check_Record_Type</startElementReference>",
            1,
        )

    # ── insert <decisions> block (if not already present) ─────────────────
    if "<name>Check_Record_Type</name>" in content:
        print("Decision 'Check_Record_Type' already present — skipping insertion.")
    else:
        # Salesforce requires all <decisions> elements to be contiguous.
        # If any exist, insert immediately before the first one.
        # Otherwise fall back to inserting before the start anchor.
        first_decision_match = re.search(r"( *<decisions>)", content)
        if first_decision_match:
            anchor = first_decision_match.group(1)
            content = content.replace(
                anchor,
                decisions_block(original_target) + anchor,
                1,
            )
        else:
            if start_format == "modern":
                anchor = "    <start>"
            else:
                anchor = "    <startElementReference>"
            content = content.replace(
                anchor,
                decisions_block(original_target) + anchor,
                1,
            )
        print("Decision block inserted.")

    # ── set apiVersion to 58.0 ───────────────────────────────────────────
    content = re.sub(r"<apiVersion>[^<]*</apiVersion>", "<apiVersion>58.0</apiVersion>", content)
    print("API version set to 58.0.")

    # ── ensure Active status ──────────────────────────────────────────────
    if re.search(r"<status>[^<]*</status>", content):
        content = re.sub(r"<status>[^<]*</status>", "<status>Active</status>", content)
    else:
        content = content.replace("</Flow>", "    <status>Active</status>\n</Flow>")
    print("Status set to Active.")

    # ── write ─────────────────────────────────────────────────────────────
    with open(flow_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    print("Flow file saved.")

    # ── confirm before deploy ─────────────────────────────────────────────
    try:
        answer = input("\nDeploy the updated flow now? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(0)

    if answer not in ("y", "yes"):
        print("Skipping deploy. File has been saved and backup is at:")
        print(f"  {backup_path}")
        sys.exit(0)

    # ── deploy ────────────────────────────────────────────────────────────
    sf_bin = shutil.which("sf") or shutil.which("sfdx")
    if not sf_bin:
        abort("Neither `sf` nor `sfdx` CLI found on PATH. Install Salesforce CLI first.")

    print(f"\nDeploying with: {sf_bin} project deploy start ...")
    result = subprocess.run(
        [sf_bin, "project", "deploy", "start", "--source-dir", flow_path],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    # Print output so the user can see what happened
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    # "Missing message metadata.transfer:Finalizing" is a known Salesforce CLI
    # cosmetic warning that fires even on successful deploys — don't treat it as
    # a failure if the component was actually deployed.
    BENIGN_ERRORS = [
        "Missing message metadata.transfer:Finalizing",
    ]

    deploy_failed = result.returncode != 0 and not any(
        msg in (result.stdout + result.stderr) for msg in BENIGN_ERRORS
    )

    if deploy_failed:
        print(
            "\nDeploy failed. Your original file has been restored from the backup.",
            file=sys.stderr,
        )
        shutil.copy2(backup_path, flow_path)
        sys.exit(result.returncode)

    print("\nDone — flow deployed and activated.")


if __name__ == "__main__":
    main()
