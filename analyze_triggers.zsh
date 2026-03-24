#!/usr/bin/env zsh
# analyze_triggers.zsh
# From a SFDC project, lists objects and fields queried or updated in triggers and their referenced Apex classes.
# Output is TSV ready to paste into Google Sheets.

TRIGGERS_DIR="${0:A:h}/../force-app/main/default/triggers"
CLASSES_DIR="${0:A:h}/../force-app/main/default/classes"

python3 - "$TRIGGERS_DIR" "$CLASSES_DIR" <<'PYTHON'
import sys, os, re
from collections import defaultdict

TRIGGERS_DIR = sys.argv[1]
CLASSES_DIR  = sys.argv[2]

# ─────────────────────────────────────────────
# Load source files
# ─────────────────────────────────────────────

def read_file(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()

# Map: class_name -> source_code  (exclude test classes)
all_classes = {}
TEST_SUFFIXES = ('_test.cls', 'test.cls', '_tests.cls', 'tests.cls')
for fname in os.listdir(CLASSES_DIR):
    if fname.endswith('.cls') and not any(fname.lower().endswith(s) for s in TEST_SUFFIXES):
        name = fname[:-4]
        all_classes[name] = read_file(os.path.join(CLASSES_DIR, fname))

# Map: trigger_name -> source_code  (only .trigger files, not -meta.xml)
all_triggers = {}
for fname in os.listdir(TRIGGERS_DIR):
    if fname.endswith('.trigger'):
        name = fname[:-8]
        all_triggers[name] = read_file(os.path.join(TRIGGERS_DIR, fname))

# ─────────────────────────────────────────────
# Helpers: strip comments and strings
# ─────────────────────────────────────────────

def strip_comments_and_strings(code):
    """Remove // line comments, /* block comments */, and string literals."""
    # Block comments
    code = re.sub(r'/\*.*?\*/', ' ', code, flags=re.DOTALL)
    # Line comments
    code = re.sub(r'//[^\n]*', ' ', code)
    # String literals
    code = re.sub(r"'(?:[^'\\]|\\.)*'", "''", code)
    return code

# ─────────────────────────────────────────────
# Trigger metadata: object + events
# ─────────────────────────────────────────────

def parse_trigger_header(code):
    """Return (trigger_name, sobject, events_string)."""
    m = re.search(
        r'\btrigger\s+(\w+)\s+on\s+(\w+)\s*\(([^)]+)\)',
        code, re.IGNORECASE
    )
    if not m:
        return None, None, None
    name   = m.group(1)
    obj    = m.group(2)
    events = ', '.join(e.strip() for e in m.group(3).split(','))
    return name, obj, events

# ─────────────────────────────────────────────
# Class discovery: find referenced classes
# ─────────────────────────────────────────────

def find_referenced_classes(code, available_classes):
    """Return set of class names mentioned in code."""
    clean = strip_comments_and_strings(code)
    found = set()
    for cname in available_classes:
        if re.search(r'\b' + re.escape(cname) + r'\b', clean):
            found.add(cname)
    return found

def collect_all_classes(seed_code, max_depth=3):
    """BFS from seed code, collect all transitively referenced local classes."""
    visited = set()
    queue   = list(find_referenced_classes(seed_code, all_classes))
    depth   = 0
    while queue and depth < max_depth:
        next_queue = []
        for cname in queue:
            if cname in visited:
                continue
            visited.add(cname)
            if cname in all_classes:
                refs = find_referenced_classes(all_classes[cname], all_classes)
                next_queue.extend(r for r in refs if r not in visited)
        queue = next_queue
        depth += 1
    return visited

# ─────────────────────────────────────────────
# SOQL extraction
# ─────────────────────────────────────────────

def extract_soql(code):
    """Return list of (sobject, [fields]) from SOQL queries in code."""
    clean = strip_comments_and_strings(code)
    results = []
    # Match [...] blocks containing SELECT
    for m in re.finditer(r'\[\s*(SELECT\b.+?)\]', clean, re.DOTALL | re.IGNORECASE):
        soql = m.group(1)

        from_m = re.search(r'\bFROM\s+(\w+)', soql, re.IGNORECASE)
        if not from_m:
            continue
        sobject = from_m.group(1)

        sel_m = re.search(r'\bSELECT\s+(.*?)\s+\bFROM\b', soql, re.DOTALL | re.IGNORECASE)
        if not sel_m:
            continue
        select_clause = sel_m.group(1)
        # Remove subqueries
        select_clause = re.sub(r'\([^)]*\)', '', select_clause)

        fields = []
        for raw in select_clause.split(','):
            f = raw.strip()
            # Accept simple field names (no spaces, valid Apex identifier)
            if f and re.match(r'^[\w.]+$', f) and f.upper() not in ('SELECT', 'FROM', 'WHERE', 'LIMIT', 'ORDER', 'GROUP'):
                fields.append(f)

        if sobject and fields:
            results.append((sobject, sorted(set(fields))))

    return results

# ─────────────────────────────────────────────
# DML extraction
# ─────────────────────────────────────────────

NON_SOBJECT_TYPES = {
    'String', 'Integer', 'Boolean', 'Decimal', 'Double', 'Long', 'Date',
    'DateTime', 'Time', 'Blob', 'Id', 'Object', 'void', 'List', 'Map',
    'Set', 'System', 'Enum', 'Type', 'Exception', 'Database', 'Schema',
    'Http', 'HttpRequest', 'HttpResponse', 'JSON', 'Math', 'Limits',
    'QueueableContext', 'BatchableContext', 'SchedulableContext',
}

def build_var_type_map(code):
    """Map variable names -> SObject type from declarations."""
    clean = strip_comments_and_strings(code)
    vmap = {}

    # List<SObjectType> varName
    for m in re.finditer(r'\bList\s*<\s*([A-Z]\w*(?:__c)?)\s*>\s+(\w+)', clean):
        stype, vname = m.group(1), m.group(2)
        if stype not in NON_SOBJECT_TYPES:
            vmap[vname] = stype

    # SObjectType varName (declaration or parameter)
    for m in re.finditer(r'\b([A-Z]\w*(?:__c)?)\s+(\w+)\s*[=;,\)\{]', clean):
        stype, vname = m.group(1), m.group(2)
        if stype not in NON_SOBJECT_TYPES and vname not in ('true', 'false', 'null', 'this', 'new'):
            if vname not in vmap:
                vmap[vname] = stype

    return vmap

def extract_new_object_fields(code):
    """Return dict: SObjectType -> set of fields used in new SObjectType(field=val) syntax."""
    clean = strip_comments_and_strings(code)
    result = defaultdict(set)
    for m in re.finditer(r'\bnew\s+([A-Z]\w*(?:__c)?)\s*\(([^)]*)\)', clean):
        stype, args = m.group(1), m.group(2)
        if stype in NON_SOBJECT_TYPES or not args.strip():
            continue
        for fm in re.finditer(r'\b(\w+)\s*=\s*[^=,]', args):
            field = fm.group(1)
            if field not in ('true', 'false', 'null') and field[0].isupper():
                result[stype].add(field)
    return result

def extract_var_field_assignments(code):
    """Return dict: varName -> set of fields assigned via var.Field = value."""
    clean = strip_comments_and_strings(code)
    result = defaultdict(set)
    for m in re.finditer(r'\b(\w+)\.(\w+)\s*=[^=]', clean):
        vname, field = m.group(1), m.group(2)
        # Field names typically start uppercase or end with __c
        if field[0].isupper() or field.endswith('__c'):
            result[vname].add(field)
    return result

DML_KEYWORDS = {
    'insert': 'Inserted',
    'update': 'Updated',
    'delete': 'Deleted',
    'upsert': 'Upserted',
    'merge':  'Merged',
}

def extract_dml(code):
    """Return list of (operation_label, sobject, [fields])."""
    clean   = strip_comments_and_strings(code)
    vmap    = build_var_type_map(code)
    new_flds = extract_new_object_fields(code)
    var_flds = extract_var_field_assignments(code)
    results  = []

    def resolve(vname):
        stype = vmap.get(vname)
        if not stype:
            return None, []
        fields = sorted(new_flds.get(stype, set()) | var_flds.get(vname, set()))
        return stype, fields

    for kw, label in DML_KEYWORDS.items():
        # Bare DML: insert varName;
        for m in re.finditer(r'\b' + kw + r'\s+(\w+)\s*;', clean, re.IGNORECASE):
            vname = m.group(1)
            if vname in ('true', 'false', 'null'):
                continue
            stype, fields = resolve(vname)
            if stype:
                results.append((label, stype, fields))
            else:
                # Could be a direct literal: insert new Account(...)
                pass

        # Database.dml(varName, ...)
        for m in re.finditer(r'\bDatabase\.' + kw + r'\s*\(\s*(\w+)', clean, re.IGNORECASE):
            vname = m.group(1)
            stype, fields = resolve(vname)
            if stype:
                results.append((label, stype, fields))

    return results

# ─────────────────────────────────────────────
# Callout detection
# ─────────────────────────────────────────────

def has_callout(code):
    clean = strip_comments_and_strings(code)
    return bool(re.search(r'\bhttp\.send\s*\(|\bcallout:\b|HttpRequest\b', clean, re.IGNORECASE))

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def emit_rows(base, sources):
    rows = []
    seen = set()

    def add(row):
        key = tuple(row)
        if key not in seen:
            seen.add(key)
            rows.append(row)

    for source_name, code in sources:
        for qobj, fields in extract_soql(code):
            add(base + [source_name, qobj, 'Queried', ', '.join(fields)])
        for op_label, dml_obj, fields in extract_dml(code):
            add(base + [source_name, dml_obj, op_label, ', '.join(fields)])
        if has_callout(code):
            add(base + [source_name, '', 'Callout', ''])

    if not rows:
        rows.append(base + ['', '', '', ''])
    for row in rows:
        print('\t'.join(row))

def main():
    headers = ['Type', 'Name', 'Trigger Object', 'Trigger Events', 'Source', 'Object', 'Operation', 'Fields']
    print('\t'.join(headers))

    # ── Triggers ──────────────────────────────────────────────────────
    for tname in sorted(all_triggers):
        trigger_code = all_triggers[tname]
        _, sobject, events = parse_trigger_header(trigger_code)
        sobject = sobject or ''
        events  = events  or ''

        referenced = collect_all_classes(trigger_code)
        sources = [('trigger file', trigger_code)] + [
            (cname, all_classes[cname])
            for cname in sorted(referenced)
            if cname in all_classes
        ]

        # Flag if any referenced class is a managed package (not in local classes)
        # by detecting namespace-qualified calls like namespace.ClassName
        managed_refs = re.findall(r'\b([a-z]\w+)\.(\w+)\s*\(', trigger_code)
        managed_note = ', '.join(sorted({f"{ns}.{cls}" for ns, cls in managed_refs})) if managed_refs else ''
        if managed_note and not referenced:
            sources += [('[managed] ' + managed_note, '')]

        emit_rows(['Trigger', tname, sobject, events], sources)

    # ── Apex Classes (non-test, not already covered as trigger sources) ──
    # Find which classes were already emitted as trigger sources
    covered = set()
    for tcode in all_triggers.values():
        covered |= collect_all_classes(tcode)

    for cname in sorted(all_classes):
        if cname in covered:
            continue
        code = all_classes[cname]

        # Detect scheduler / queueable / batchable type from class declaration
        class_type = 'Apex Class'
        if re.search(r'\bimplements\b.*\bSchedulable\b', code, re.IGNORECASE):
            class_type = 'Apex Schedulable'
        elif re.search(r'\bimplements\b.*\bQueueable\b', code, re.IGNORECASE):
            class_type = 'Apex Queueable'
        elif re.search(r'\bimplements\b.*\bDatabase\.Batchable\b', code, re.IGNORECASE):
            class_type = 'Apex Batchable'
        elif re.search(r'@InvocableMethod\b', code):
            class_type = 'Apex Invocable'

        emit_rows([class_type, cname, '', ''], [(cname, code)])

main()
PYTHON
