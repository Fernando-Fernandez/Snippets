#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OBJECTS_DIR="$PROJECT_ROOT/force-app/main/default/objects"

# Verify this looks like a Salesforce project root
if [ ! -f "$PROJECT_ROOT/sfdx-project.json" ] && [ ! -f "$PROJECT_ROOT/package.json" ]; then
  echo "Error: Could not find a Salesforce project root at $PROJECT_ROOT"
  echo "       Expected sfdx-project.json or package.json to be present."
  exit 1
fi

if [ ! -d "$OBJECTS_DIR" ]; then
  echo "Error: Objects directory not found at $OBJECTS_DIR"
  exit 1
fi

for object_dir in "$OBJECTS_DIR"/*/; do
  object_name=$(basename "$object_dir")
  vr_dir="$object_dir/validationRules"

  [ -d "$vr_dir" ] || continue

  for vr_file in "$vr_dir"/*.xml; do
    [ -f "$vr_file" ] || continue

    active=$(grep -o '<active>[^<]*</active>' "$vr_file" | sed 's/<[^>]*>//g')
    [ "$active" = "true" ] || continue

    rule_name=$(grep -o '<fullName>[^<]*</fullName>' "$vr_file" | sed 's/<[^>]*>//g')
    description=$(grep -o '<description>[^<]*</description>' "$vr_file" | sed 's/<[^>]*>//g')
    error_message=$(grep -o '<errorMessage>[^<]*</errorMessage>' "$vr_file" | sed 's/<[^>]*>//g')

    echo "Object:       $object_name"
    echo "Rule:         $rule_name"
    echo "Description:  $description"
    echo "Error Msg:    $error_message"
    echo "--------------------"
  done
done
