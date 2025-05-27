#!/usr/bin/env bash
#
# For each *.cls file in the current directory, create a file with the same
# base name and extension ".cls-meta.xml" containing the specified XML.

for cls_file in *.cls; do
    # If there are no .cls files, the glob won't match. Check if file actually exists.
    [[ -e "$cls_file" ]] || continue

    # Use parameter expansion to remove the .cls extension, then add .cls-meta.xml
    meta_file="${cls_file%.cls}.cls-meta.xml"

    cat <<EOF > "$meta_file"
<?xml version="1.0" encoding="UTF-8"?>
<ApexClass xmlns="http://soap.sforce.com/2006/04/metadata">
    <apiVersion>58.0</apiVersion>
    <status>Active</status>
</ApexClass>
EOF

    echo "Created $meta_file"
done
