#!/usr/bin/env python3
"""
Salesforce Profile Permission Comparator
Compares SDC profile permissions between two Salesforce orgs.

Usage:
    python3 compare_profiles.py --source-org <source-alias> --target-org <target-alias>

Example:
    python3 compare_profiles.py --source-org prod --target-org sandbox

User can use --skip-retrieval flag to reuse existing files: 
    python3 compare_profiles.py --source-org <alias> --target-org <alias> --skip-retrieval

"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

# ANSI color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

# Configuration
# Map target org profile names to source org profile names
# Format: "Target Profile Name": "Source Profile Name"
# Note: Use actual profile names with & (not %26) - Salesforce will handle encoding
PROFILE_MAPPINGS = {
    "SDC - Events & Marketing": "Events & Marketing",
    "SDC - Standard User": "Sales"
}

OBJECTS_TO_COMPARE = [
    "User",
    "Account",
    "Lead",
    "Contact",
    "Opportunity",
    "Product2",
    "Pricebook2",
    "Event",
    "Task",
    "Invoice__c"
]

COMPARISON_DIR = ".profile-comparison"
SOURCE_DIR = os.path.join(COMPARISON_DIR, "source")
TARGET_DIR = os.path.join(COMPARISON_DIR, "target")


def print_colored(message: str, color: str = Colors.ENDC):
    """Print colored message to console."""
    print(f"{color}{message}{Colors.ENDC}")


def print_step(step_num: int, total_steps: int, message: str):
    """Print step progress."""
    print_colored(f"\n[{step_num}/{total_steps}] {message}", Colors.BOLD + Colors.BLUE)


def run_sfdx_command(command: List[str]) -> Tuple[bool, str]:
    """
    Execute an SFDX CLI command and return success status and output.
    
    Args:
        command: List of command arguments
        
    Returns:
        Tuple of (success: bool, output: str)
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr
            
    except Exception as e:
        return False, str(e)


def clean_profile_name(profile_name: str) -> str:
    """Convert profile name to safe filename format."""
    return profile_name.replace(" ", "_").replace("&", "and").replace("-", "")


def retrieve_profiles(org_alias: str, output_dir: str, profile_names: List[str]) -> bool:
    """
    Retrieve profiles from a Salesforce org.
    
    Args:
        org_alias: Salesforce org alias
        output_dir: Directory to store retrieved profiles (not used - sf retrieves to default location)
        profile_names: List of profile names to retrieve
        
    Returns:
        True if successful, False otherwise
    """
    print_colored(f"  Retrieving profiles from org: {org_alias}", Colors.YELLOW)
    
    # Retrieve profiles one at a time to avoid shell parsing issues with special characters
    default_profiles_dir = os.path.join("force-app", "main", "default", "profiles")
    target_profiles_dir = os.path.join(output_dir, "profiles")
    os.makedirs(target_profiles_dir, exist_ok=True)
    
    retrieved_count = 0
    for profile_name in profile_names:
        print_colored(f"  Retrieving: {profile_name}", Colors.YELLOW)
        
        # Build SFDX command for single profile - retrieve to default location (force-app)
        command = [
            "sf", "project", "retrieve", "start",
            "--metadata", f'Profile:{profile_name}',
            "--target-org", org_alias
        ]
        print_colored(f"  Retrieving profiles {' '.join(command)}", Colors.BLUE)
        
        success, output = run_sfdx_command(command)
        
        if not success:
            print_colored(f"  ✗ Failed to retrieve profile: {profile_name}", Colors.RED)
            print_colored(f"  Error: {output}", Colors.RED)
            continue
        
        # Copy the retrieved file immediately
        if os.path.exists(default_profiles_dir):
            copied = False
            for filename in os.listdir(default_profiles_dir):
                if filename.endswith('.profile-meta.xml'):
                    src = os.path.join(default_profiles_dir, filename)
                    dst = os.path.join(target_profiles_dir, filename)
                    shutil.copy2(src, dst)
                    print_colored(f"    Copied: {filename}", Colors.GREEN)
                    # Delete the source file to prevent conflicts
                    os.remove(src)
                    copied = True
                    retrieved_count += 1
            
            if not copied:
                print_colored(f"  ✗ No profile file found after retrieval for: {profile_name}", Colors.RED)
        else:
            print_colored(f"  ✗ Profiles directory not found after retrieval", Colors.RED)
    
    if retrieved_count == 0:
        print_colored(f"  ✗ No profiles were successfully retrieved", Colors.RED)
        return False
    
    print_colored(f"  ✓ Successfully retrieved {retrieved_count} profile(s) from {org_alias}", Colors.GREEN)
    return True
    


def parse_profile_xml(profile_path: str) -> Dict:
    """
    Parse a Salesforce profile XML file and extract permissions.
    
    Args:
        profile_path: Path to profile XML file
        
    Returns:
        Dictionary containing profile permissions
    """
    try:
        tree = ET.parse(profile_path)
        root = tree.getroot()
        
        # Define namespace
        ns = {'sf': 'http://soap.sforce.com/2006/04/metadata'}
        
        profile_data = {
            'field_permissions': {},
            'object_permissions': {}
        }
        
        # Extract field permissions
        for field_perm in root.findall('.//sf:fieldPermissions', ns):
            field = field_perm.find('sf:field', ns)
            editable = field_perm.find('sf:editable', ns)
            readable = field_perm.find('sf:readable', ns)
            
            if field is not None:
                field_name = field.text
                profile_data['field_permissions'][field_name] = {
                    'editable': editable.text.lower() == 'true' if editable is not None else False,
                    'readable': readable.text.lower() == 'true' if readable is not None else False
                }
        
        # Extract object permissions
        for obj_perm in root.findall('.//sf:objectPermissions', ns):
            obj = obj_perm.find('sf:object', ns)
            
            if obj is not None:
                obj_name = obj.text
                profile_data['object_permissions'][obj_name] = {
                    'allowCreate': obj_perm.find('sf:allowCreate', ns).text.lower() == 'true' 
                                   if obj_perm.find('sf:allowCreate', ns) is not None else False,
                    'allowDelete': obj_perm.find('sf:allowDelete', ns).text.lower() == 'true'
                                   if obj_perm.find('sf:allowDelete', ns) is not None else False,
                    'allowEdit': obj_perm.find('sf:allowEdit', ns).text.lower() == 'true'
                                 if obj_perm.find('sf:allowEdit', ns) is not None else False,
                    'allowRead': obj_perm.find('sf:allowRead', ns).text.lower() == 'true'
                                 if obj_perm.find('sf:allowRead', ns) is not None else False,
                    'modifyAllRecords': obj_perm.find('sf:modifyAllRecords', ns).text.lower() == 'true'
                                        if obj_perm.find('sf:modifyAllRecords', ns) is not None else False,
                    'viewAllRecords': obj_perm.find('sf:viewAllRecords', ns).text.lower() == 'true'
                                      if obj_perm.find('sf:viewAllRecords', ns) is not None else False
                }
        
        return profile_data
        
    except Exception as e:
        print_colored(f"Error parsing profile XML: {e}", Colors.RED)
        return None


def compare_field_permissions(source_data: Dict, target_data: Dict, objects: List[str]) -> List[Dict]:
    """
    Compare field permissions between source and target profiles.
    
    Args:
        source_data: Source profile data
        target_data: Target profile data
        objects: List of objects to compare
        
    Returns:
        List of comparison results
    """
    results = []
    
    # Get all fields for specified objects
    all_fields = set()
    for field in source_data['field_permissions'].keys():
        if any(field.startswith(f"{obj}.") for obj in objects):
            all_fields.add(field)
    for field in target_data['field_permissions'].keys():
        if any(field.startswith(f"{obj}.") for obj in objects):
            all_fields.add(field)
    
    # Compare each field
    for field in sorted(all_fields):
        obj_name = field.split('.')[0]
        field_name = field.split('.')[1] if '.' in field else field
        
        source_perm = source_data['field_permissions'].get(field, {'readable': False, 'editable': False})
        target_perm = target_data['field_permissions'].get(field, {'readable': False, 'editable': False})
        
        has_difference = (
            source_perm['readable'] != target_perm['readable'] or
            source_perm['editable'] != target_perm['editable']
        )
        
        results.append({
            'Object': obj_name,
            'Field': field_name,
            'Source_Readable': 'Yes' if source_perm['readable'] else 'No',
            'Source_Editable': 'Yes' if source_perm['editable'] else 'No',
            'Target_Readable': 'Yes' if target_perm['readable'] else 'No',
            'Target_Editable': 'Yes' if target_perm['editable'] else 'No',
            'Has_Difference': 'YES' if has_difference else 'No',
            'Difference_Details': get_field_diff_details(source_perm, target_perm) if has_difference else ''
        })
    
    return results


def get_field_diff_details(source: Dict, target: Dict) -> str:
    """Generate human-readable difference details for field permissions."""
    details = []
    
    if source['readable'] != target['readable']:
        details.append(f"Read: {source['readable']} → {target['readable']}")
    if source['editable'] != target['editable']:
        details.append(f"Edit: {source['editable']} → {target['editable']}")
    
    return "; ".join(details)


def compare_object_permissions(source_data: Dict, target_data: Dict, objects: List[str]) -> List[Dict]:
    """
    Compare object permissions between source and target profiles.
    
    Args:
        source_data: Source profile data
        target_data: Target profile data
        objects: List of objects to compare
        
    Returns:
        List of comparison results
    """
    results = []
    
    for obj in objects:
        source_perm = source_data['object_permissions'].get(obj, {
            'allowCreate': False,
            'allowDelete': False,
            'allowEdit': False,
            'allowRead': False,
            'modifyAllRecords': False,
            'viewAllRecords': False
        })
        
        target_perm = target_data['object_permissions'].get(obj, {
            'allowCreate': False,
            'allowDelete': False,
            'allowEdit': False,
            'allowRead': False,
            'modifyAllRecords': False,
            'viewAllRecords': False
        })
        
        has_difference = any([
            source_perm[key] != target_perm[key]
            for key in ['allowCreate', 'allowDelete', 'allowEdit', 'allowRead', 
                       'modifyAllRecords', 'viewAllRecords']
        ])
        
        results.append({
            'Object': obj,
            'Source_Create': 'Yes' if source_perm['allowCreate'] else 'No',
            'Source_Read': 'Yes' if source_perm['allowRead'] else 'No',
            'Source_Edit': 'Yes' if source_perm['allowEdit'] else 'No',
            'Source_Delete': 'Yes' if source_perm['allowDelete'] else 'No',
            'Source_ViewAll': 'Yes' if source_perm['viewAllRecords'] else 'No',
            'Source_ModifyAll': 'Yes' if source_perm['modifyAllRecords'] else 'No',
            'Target_Create': 'Yes' if target_perm['allowCreate'] else 'No',
            'Target_Read': 'Yes' if target_perm['allowRead'] else 'No',
            'Target_Edit': 'Yes' if target_perm['allowEdit'] else 'No',
            'Target_Delete': 'Yes' if target_perm['allowDelete'] else 'No',
            'Target_ViewAll': 'Yes' if target_perm['viewAllRecords'] else 'No',
            'Target_ModifyAll': 'Yes' if target_perm['modifyAllRecords'] else 'No',
            'Has_Difference': 'YES' if has_difference else 'No',
            'Difference_Details': get_object_diff_details(source_perm, target_perm) if has_difference else ''
        })
    
    return results


def get_object_diff_details(source: Dict, target: Dict) -> str:
    """Generate human-readable difference details for object permissions."""
    details = []
    perm_names = {
        'allowCreate': 'Create',
        'allowRead': 'Read',
        'allowEdit': 'Edit',
        'allowDelete': 'Delete',
        'viewAllRecords': 'ViewAll',
        'modifyAllRecords': 'ModifyAll'
    }
    
    for key, label in perm_names.items():
        if source.get(key, False) != target.get(key, False):
            details.append(f"{label}: {source.get(key, False)} → {target.get(key, False)}")
    
    return "; ".join(details)


def write_csv_report(filename: str, data: List[Dict], headers: List[str] = None):
    """
    Write comparison results to CSV file.
    
    Args:
        filename: Output CSV filename
        data: List of dictionaries to write
        headers: Optional list of headers (uses keys from first dict if not provided)
    """
    if not data:
        print_colored(f"  Warning: No data to write to {filename}", Colors.YELLOW)
        return
    
    if headers is None:
        headers = list(data[0].keys())
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        writer.writerows(data)
    
    print_colored(f"  ✓ Created: {filename}", Colors.GREEN)


def generate_summary(field_results: Dict[str, List[Dict]], 
                     object_results: Dict[str, List[Dict]]) -> List[Dict]:
    """
    Generate summary statistics for the comparison.
    
    Args:
        field_results: Field permission comparison results by profile
        object_results: Object permission comparison results by profile
        
    Returns:
        List of summary dictionaries
    """
    summary = []
    
    for profile_name in field_results.keys():
        field_data = field_results[profile_name]
        object_data = object_results[profile_name]
        
        total_fields = len(field_data)
        different_fields = sum(1 for row in field_data if row['Has_Difference'] == 'YES')
        
        total_objects = len(object_data)
        different_objects = sum(1 for row in object_data if row['Has_Difference'] == 'YES')
        
        summary.append({
            'Profile': profile_name,
            'Total_Fields_Compared': total_fields,
            'Fields_With_Differences': different_fields,
            'Fields_Match_Percentage': f"{((total_fields - different_fields) / total_fields * 100):.1f}%" if total_fields > 0 else "N/A",
            'Total_Objects_Compared': total_objects,
            'Objects_With_Differences': different_objects,
            'Objects_Match_Percentage': f"{((total_objects - different_objects) / total_objects * 100):.1f}%" if total_objects > 0 else "N/A"
        })
    
    return summary


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Compare SDC profile permissions between two Salesforce orgs.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python compare_sdc_profiles.py --source-org prod --target-org sandbox
  python compare_sdc_profiles.py --source-org myorg1 --target-org myorg2
  python compare_sdc_profiles.py --source-org prod --target-org sandbox --skip-retrieval
        """
    )
    parser.add_argument('--source-org', required=True, help='Source org alias')
    parser.add_argument('--target-org', required=True, help='Target org alias')
    parser.add_argument('--skip-retrieval', action='store_true', 
                        help='Skip profile retrieval and use existing files in .profile-comparison folder')
    
    args = parser.parse_args()
    
    print_colored("\n" + "="*70, Colors.BOLD)
    print_colored("  Salesforce Profile Permission Comparator", Colors.BOLD + Colors.BLUE)
    print_colored("="*70 + "\n", Colors.BOLD)
    
    print_colored(f"Source Org: {args.source_org}", Colors.YELLOW)
    print_colored(f"Target Org: {args.target_org}", Colors.YELLOW)
    print_colored(f"\nProfile Mappings:", Colors.YELLOW)
    for target_profile, source_profile in PROFILE_MAPPINGS.items():
        print_colored(f"  Target '{target_profile}' → Source '{source_profile}'", Colors.YELLOW)
    print_colored(f"\nObjects: {', '.join(OBJECTS_TO_COMPARE)}\n", Colors.YELLOW)
    
    if args.skip_retrieval:
        # Step 1: Check if comparison directories exist
        print_step(1, 6, "Checking for existing profile files")
        if not os.path.exists(COMPARISON_DIR):
            print_colored(f"\n✗ Comparison directory not found: {COMPARISON_DIR}", Colors.RED)
            print_colored("Please run without --skip-retrieval first to retrieve profiles.", Colors.YELLOW)
            sys.exit(1)
        
        if not os.path.exists(os.path.join(SOURCE_DIR, "profiles")):
            print_colored(f"\n✗ Source profiles directory not found: {os.path.join(SOURCE_DIR, 'profiles')}", Colors.RED)
            sys.exit(1)
        
        if not os.path.exists(os.path.join(TARGET_DIR, "profiles")):
            print_colored(f"\n✗ Target profiles directory not found: {os.path.join(TARGET_DIR, 'profiles')}", Colors.RED)
            sys.exit(1)
        
        print_colored("  ✓ Using existing profile files", Colors.GREEN)
        
        # Step 2-3: Skip retrieval
        print_step(2, 6, "Skipping profile retrieval (using existing files)")
        print_step(3, 6, "Skipping profile retrieval (using existing files)")
        
    else:
        # Step 1: Clean up old comparison directory
        print_step(1, 6, "Preparing comparison directories")
        if os.path.exists(COMPARISON_DIR):
            shutil.rmtree(COMPARISON_DIR)
        os.makedirs(SOURCE_DIR, exist_ok=True)
        os.makedirs(TARGET_DIR, exist_ok=True)
        print_colored("  ✓ Directories ready", Colors.GREEN)
        
        # Step 2: Retrieve profiles from source org
        print_step(2, 6, "Retrieving profiles from source org")
        source_profiles = list(set(PROFILE_MAPPINGS.values()))  # Get unique source profile names
        if not retrieve_profiles(args.source_org, SOURCE_DIR, source_profiles):
            print_colored("\n✗ Failed to retrieve profiles from source org. Exiting.", Colors.RED)
            sys.exit(1)
        
        # Debug: Show what was actually created in SOURCE_DIR
        print_colored(f"\n  DEBUG: Listing contents of SOURCE_DIR: {SOURCE_DIR}", Colors.YELLOW)
        for root, dirs, files in os.walk(SOURCE_DIR):
            level = root.replace(SOURCE_DIR, '').count(os.sep)
            indent = ' ' * 2 * level
            print_colored(f"  {indent}{os.path.basename(root)}/", Colors.YELLOW)
            subindent = ' ' * 2 * (level + 1)
            for file in files:
                print_colored(f"  {subindent}{file}", Colors.YELLOW)
        
        # Step 3: Retrieve profiles from target org
        print_step(3, 6, "Retrieving profiles from target org")
        target_profiles = list(PROFILE_MAPPINGS.keys())  # Get target profile names
        if not retrieve_profiles(args.target_org, TARGET_DIR, target_profiles):
            print_colored("\n✗ Failed to retrieve profiles from target org. Exiting.", Colors.RED)
            sys.exit(1)
        
        # Debug: Show what was actually created in TARGET_DIR
        print_colored(f"\n  DEBUG: Listing contents of TARGET_DIR: {TARGET_DIR}", Colors.YELLOW)
        for root, dirs, files in os.walk(TARGET_DIR):
            level = root.replace(TARGET_DIR, '').count(os.sep)
            indent = ' ' * 2 * level
            print_colored(f"  {indent}{os.path.basename(root)}/", Colors.YELLOW)
            subindent = ' ' * 2 * (level + 1)
            for file in files:
                print_colored(f"  {subindent}{file}", Colors.YELLOW)
    
    # Step 4: Parse and compare profiles
    print_step(4, 6, "Parsing and comparing profiles")
    
    field_comparison_results = {}
    object_comparison_results = {}
    
    for target_profile_name, source_profile_name in PROFILE_MAPPINGS.items():
        print_colored(f"\n  Comparing: Target '{target_profile_name}' ↔ Source '{source_profile_name}'", Colors.YELLOW)
        
        # Debug: List what files actually exist
        source_profiles_dir = os.path.join(SOURCE_DIR, "profiles")
        target_profiles_dir = os.path.join(TARGET_DIR, "profiles")
        
        if os.path.exists(source_profiles_dir):
            source_files = os.listdir(source_profiles_dir)
            print_colored(f"    DEBUG: Source profiles directory contains: {source_files}", Colors.YELLOW)
        else:
            print_colored(f"    DEBUG: Source profiles directory does not exist: {source_profiles_dir}", Colors.RED)
            
        if os.path.exists(target_profiles_dir):
            target_files = os.listdir(target_profiles_dir)
            print_colored(f"    DEBUG: Target profiles directory contains: {target_files}", Colors.YELLOW)
        else:
            print_colored(f"    DEBUG: Target profiles directory does not exist: {target_profiles_dir}", Colors.RED)
        
        # Construct profile file paths - Salesforce keeps spaces as spaces
        # and URL-encodes special characters like & (%26) in filenames
        source_profile_filename = f"{source_profile_name.replace('&', '%26')}.profile-meta.xml"
        target_profile_filename = f"{target_profile_name.replace('&', '%26')}.profile-meta.xml"
        
        print_colored(f"    DEBUG: Looking for source file: {source_profile_filename}", Colors.YELLOW)
        print_colored(f"    DEBUG: Looking for target file: {target_profile_filename}", Colors.YELLOW)
        
        source_profile_path = os.path.join(SOURCE_DIR, "profiles", source_profile_filename)
        target_profile_path = os.path.join(TARGET_DIR, "profiles", target_profile_filename)
        
        print_colored(f"    DEBUG: Full source path: {source_profile_path}", Colors.YELLOW)
        print_colored(f"    DEBUG: Full target path: {target_profile_path}", Colors.YELLOW)
        
        # Check if files exist
        if not os.path.exists(source_profile_path):
            print_colored(f"    ✗ Profile not found in source org: {source_profile_filename}", Colors.RED)
            continue
        if not os.path.exists(target_profile_path):
            print_colored(f"    ✗ Profile not found in target org: {target_profile_filename}", Colors.RED)
            continue
        
        # Parse profiles
        source_data = parse_profile_xml(source_profile_path)
        target_data = parse_profile_xml(target_profile_path)
        
        if source_data is None or target_data is None:
            print_colored(f"    ✗ Failed to parse profiles", Colors.RED)
            continue
        
        # Compare permissions
        field_results = compare_field_permissions(source_data, target_data, OBJECTS_TO_COMPARE)
        object_results = compare_object_permissions(source_data, target_data, OBJECTS_TO_COMPARE)
        
        # Store results using target profile name as key
        field_comparison_results[target_profile_name] = field_results
        object_comparison_results[target_profile_name] = object_results
        
        # Count differences
        field_diffs = sum(1 for row in field_results if row['Has_Difference'] == 'YES')
        object_diffs = sum(1 for row in object_results if row['Has_Difference'] == 'YES')
        
        print_colored(f"    ✓ Fields compared: {len(field_results)} ({field_diffs} differences)", Colors.GREEN)
        print_colored(f"    ✓ Objects compared: {len(object_results)} ({object_diffs} differences)", Colors.GREEN)
    
    # Check if any profiles were successfully compared
    if not field_comparison_results:
        print_colored("\n✗ No profiles were successfully compared!", Colors.RED)
        print_colored(f"\nTemporary files preserved in: {COMPARISON_DIR}/", Colors.YELLOW)
        print_colored("Please review the debug output above to troubleshoot the issue.", Colors.YELLOW)
        sys.exit(1)
    
    # Step 5: Generate reports
    print_step(5, 6, "Generating CSV reports")
    
    # Create output directory with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"profile-comparison-report-{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    
    # Write individual profile reports
    for target_profile_name in field_comparison_results.keys():
        safe_name = clean_profile_name(target_profile_name)
        
        # Field permissions CSV
        field_csv = os.path.join(output_dir, f"field_permissions_{safe_name}.csv")
        write_csv_report(field_csv, field_comparison_results[target_profile_name])
        
        # Object permissions CSV
        object_csv = os.path.join(output_dir, f"object_permissions_{safe_name}.csv")
        write_csv_report(object_csv, object_comparison_results[target_profile_name])
    
    # Generate and write summary
    summary_data = generate_summary(field_comparison_results, object_comparison_results)
    summary_csv = os.path.join(output_dir, "summary_report.csv")
    write_csv_report(summary_csv, summary_data)
    
    # Step 6: Cleanup
    if not args.skip_retrieval:
        print_step(6, 6, "Cleaning up temporary files")
        shutil.rmtree(COMPARISON_DIR)
        print_colored("  ✓ Cleanup complete", Colors.GREEN)
    else:
        print_step(6, 6, "Preserving comparison files")
        print_colored(f"  ℹ Comparison files preserved in: {COMPARISON_DIR}/", Colors.YELLOW)
    
    # Final summary
    print_colored("\n" + "="*70, Colors.BOLD)
    print_colored("  Comparison Complete!", Colors.BOLD + Colors.GREEN)
    print_colored("="*70 + "\n", Colors.BOLD)
    
    print_colored(f"Reports generated in: {output_dir}/", Colors.BOLD)
    print_colored(f"  • summary_report.csv", Colors.GREEN)
    for target_profile_name in field_comparison_results.keys():
        safe_name = clean_profile_name(target_profile_name)
        print_colored(f"  • field_permissions_{safe_name}.csv", Colors.GREEN)
        print_colored(f"  • object_permissions_{safe_name}.csv", Colors.GREEN)
    
    print_colored("\nSummary Statistics:", Colors.BOLD)
    for summary in summary_data:
        print_colored(f"\n  {summary['Profile']}:", Colors.YELLOW)
        print_colored(f"    Fields: {summary['Fields_With_Differences']}/{summary['Total_Fields_Compared']} differences ({summary['Fields_Match_Percentage']} match)", Colors.YELLOW)
        print_colored(f"    Objects: {summary['Objects_With_Differences']}/{summary['Total_Objects_Compared']} differences ({summary['Objects_Match_Percentage']} match)", Colors.YELLOW)
    
    print("\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_colored("\n\nOperation cancelled by user.", Colors.YELLOW)
        sys.exit(0)
    except Exception as e:
        print_colored(f"\n✗ Unexpected error: {e}", Colors.RED)
        import traceback
        traceback.print_exc()
        sys.exit(1)
