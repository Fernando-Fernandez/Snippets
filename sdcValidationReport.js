#!/usr/bin/env node
/**
 * SDC Validation Rule Relevance Report
 * - Scans local Salesforce metadata (source format) to find ACTIVE validation rules
 *   for specified objects and determines relevance for SDC-prefixed record types
 *   based on whether any fields referenced in the rule appear on any SDC layout assignment.
 *
 * Defaults per user:
 * - Record type match on API Name ONLY (fullName starts with SDC)
 * - Relevant if a referenced field is present on ANY SDC layout assignment (across profiles)
 *
 * Usage:
 *   node scripts/sdcValidationReport.js
 *   node scripts/sdcValidationReport.js --objects "Account,Lead,Contact,Opportunity,Campaign,User,Invoice__c,Task,Event" --sdcPrefix "SDC" --root "force-app/main/default" --includeInactive --verbose
 *
 * Outputs:
 *   - reports/sdc-validation-rules.csv
 *   - reports/sdc-validation-rules.md
 *   - reports/details/<Object>/rules.json
 *   - reports/details/<Object>/sdc-recordTypes.json
 *   - reports/details/<Object>/sdc-layouts.json
 *   - reports/details/<Object>/layout-fields.json
 */

const fs = require('fs');
const fsp = require('fs/promises');
const path = require('path');

const DEFAULT_ROOT = 'force-app/main/default';
const DEFAULT_OBJECTS = [
  'Account',
  'Lead',
  'Contact',
  'Opportunity',
  'Campaign',
  'User',
  'Invoice__c',
  'Task',
  'Event',
];
const DEFAULT_SDC_PREFIX = 'SDC';

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = {
    root: DEFAULT_ROOT,
    objects: DEFAULT_OBJECTS,
    sdcPrefix: DEFAULT_SDC_PREFIX,
    includeInactive: false,
    verbose: false,
  };
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === '--root' && args[i + 1]) {
      opts.root = args[++i];
    } else if (a === '--objects' && args[i + 1]) {
      opts.objects = args[++i].split(',').map(s => s.trim()).filter(Boolean);
    } else if (a === '--sdcPrefix' && args[i + 1]) {
      opts.sdcPrefix = args[++i];
    } else if (a === '--includeInactive') {
      opts.includeInactive = true;
    } else if (a === '--verbose') {
      opts.verbose = true;
    }
  }
  return opts;
}

function logv(verbose, ...args) {
  if (verbose) console.log('[sdcReport]', ...args);
}

async function ensureDir(p) {
  await fsp.mkdir(p, { recursive: true });
}

function xmlTextBetween(tag, xml) {
  const m = xml.match(new RegExp(`<${tag}>([\\s\\S]*?)<\\/${tag}>`));
  return m ? m[1].trim() : null;
}

function xmlAllBetween(tag, xml) {
  const re = new RegExp(`<${tag}>([\\s\\S]*?)<\\/${tag}>`, 'g');
  const out = [];
  let m;
  while ((m = re.exec(xml)) !== null) {
    out.push(m[1].trim());
  }
  return out;
}

function getTagBlocks(tag, xml) {
  // Return array of raw contents inside each <tag>...</tag>
  const re = new RegExp(`<${tag}\\b[^>]*>([\\s\\S]*?)<\\/${tag}>`, 'g');
  const out = [];
  let m;
  while ((m = re.exec(xml)) !== null) {
    out.push(m[1]);
  }
  return out;
}

async function readIfExists(file) {
  try {
    return await fsp.readFile(file, 'utf8');
  } catch (e) {
    return null;
  }
}

async function listFilesRec(dir) {
  const out = [];
  async function walk(d) {
    let ents = [];
    try {
      ents = await fsp.readdir(d, { withFileTypes: true });
    } catch (e) {
      return;
    }
    for (const ent of ents) {
      const full = path.join(d, ent.name);
      if (ent.isDirectory()) {
        await walk(full);
      } else {
        out.push(full);
      }
    }
  }
  await walk(dir);
  return out;
}

function parseValidationRuleXml(xml) {
  return {
    fullName: xmlTextBetween('fullName', xml),
    active: (xmlTextBetween('active', xml) || '').toLowerCase() === 'true',
    description: xmlTextBetween('description', xml),
    errorDisplayField: xmlTextBetween('errorDisplayField', xml),
    errorConditionFormula: xmlTextBetween('errorConditionFormula', xml) || '',
  };
}

function parseRecordTypeXml(xml) {
  return {
    fullName: xmlTextBetween('fullName', xml),
    label: xmlTextBetween('label', xml),
    // layoutAssignments exist at profile level, not in recordType metadata
  };
}

function parseProfileLayoutAssignments(xml, objectApiName) {
  // Returns array of { layout, recordType } strings for this object
  // layoutAssignments entries can contain object and recordType; but SFDC source for classic profiles stores:
  //   <layoutAssignments><layout>Object-LayoutName</layout><recordType>Object.RecordTypeApiName</recordType></layoutAssignments>
  const blocks = getTagBlocks('layoutAssignments', xml);
  const out = [];
  for (const b of blocks) {
    const layout = xmlTextBetween('layout', b);
    const recordType = xmlTextBetween('recordType', b); // Object.RecordTypeApiName or absent
    if (layout && layout.startsWith(objectApiName + '-')) {
      out.push({ layout, recordType });
    }
  }
  return out;
}

function parseLayoutFields(xml) {
  // Extract fields present in detail layout sections.
  // Handles both:
  //  - <detailLayoutSections><layoutColumns><layoutItems><field>Field__c</field>
  //  - <layoutSections><layoutColumns><layoutItems><field>Field__c</field>
  const fields = new Set();

  // 1) Classic pattern: <detailLayoutSections> ... <layoutItems><field>...</field>
  const detailSectionBlocks = getTagBlocks('detailLayoutSections', xml);
  for (const sec of detailSectionBlocks) {
    const itemBlocks = getTagBlocks('layoutItems', sec);
    for (const it of itemBlocks) {
      const f = xmlTextBetween('field', it);
      if (f) fields.add(f.trim());
    }
  }

  // 2) Retrieved metadata often uses <layoutSections> for the main sections.
  //    Parse the same structure under <layoutSections>.
  const layoutSectionBlocks = getTagBlocks('layoutSections', xml);
  for (const sec of layoutSectionBlocks) {
    const itemBlocks = getTagBlocks('layoutItems', sec);
    for (const it of itemBlocks) {
      const f = xmlTextBetween('field', it);
      if (f) fields.add(f.trim());
    }
  }

  return fields;
}

const FORMULA_KEYWORDS = new Set([
  'AND','OR','NOT','IF','ISBLANK','ISNULL','ISCHANGED','PRIORVALUE','ISNEW','CASE','TEXT',
  'ISPICKVAL','VLOOKUP','LEN','VALUE','BLANKVALUE','NULLVALUE','BEGINS','CONTAINS','INCLUDES','ISNUMBER',
  'TODAY','NOW','DATE','DATETIMEVALUE','DATEVALUE','TIMEVALUE','YEAR','MONTH','DAY','HOUR','MINUTE','SECOND',
  'TRUE','FALSE','NULL','ISCLONE',
]);

const GLOBAL_VARS = ['$User', '$Profile', '$Organization', '$Setup', '$Permission', '$Api', '$Label', '$System', '$UserRole', '$Profile', '$Record', '$Tenant'];

function parseFieldsFromFormula(formula, baseObject) {
  // Heuristics to pull base-object fields from a validation rule formula.
  // Exclude obvious non-fields (functions, string/numeric literals, global vars, relationships).
  if (!formula) return new Set();
  let f = formula;

  // Remove string literals
  f = f.replace(/"([^"\\]|\\.)*"|'([^'\\]|\\.)*'/g, ' ');

  // Replace punctuation/operators with space
  f = f.replace(/[\+\-\*\/\^\&\|\!\=\<\>\(\)\,\.\:\?\n\r\t\[\]]/g, ' ');

  // Split into tokens
  const tokens = f.split(/\s+/).filter(Boolean);

  const fields = new Set();

  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];

    // Skip numbers
    if (/^[0-9]+(\.[0-9]+)?$/.test(t)) continue;

    // Global variables or $Record.* etc.
    if (t.startsWith('$')) continue;
    if (GLOBAL_VARS.includes(t)) continue;

    // Functions/keywords
    if (FORMULA_KEYWORDS.has(t.toUpperCase())) continue;

    // Relationship indicators were removed by punctuation, but we still want to ignore obvious
    // non-field tokens like RecordType, Owner, CreatedById unless clearly a base field.
    // We will accept typical field API names: include those ending with __c, or standard field-like names with camel or caps.
    const looksLikeField = /__c$/.test(t) || /^[A-Za-z][A-Za-z0-9_]*$/.test(t);

    if (!looksLikeField) continue;

    // Common non-layout tokens to exclude:
    if (['RecordType', 'RecordTypeId', 'RecordTypeId__c', 'Id', 'Owner', 'OwnerId', 'CreatedById', 'LastModifiedById'].includes(t)) {
      // These can be on layout but typically not; we conservatively exclude OwnerId/Id/CreatedById etc.
      // If needed, adjust this list.
      continue;
    }

    fields.add(t);
  }

  return fields;
}

function csvEscape(val) {
  if (val == null) return '';
  const s = String(val);
  if (s.includes(',') || s.includes('"') || s.includes('\n')) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

async function main() {
  const opts = parseArgs();
  const { root, objects, sdcPrefix, includeInactive, verbose } = opts;

  const OUTPUT_DIR = path.join('reports');
  const DETAILS_DIR = path.join(OUTPUT_DIR, 'details');

  await ensureDir(OUTPUT_DIR);
  await ensureDir(DETAILS_DIR);

  const allProfilesDir = path.join(root, 'profiles');
  const layoutsDir = path.join(root, 'layouts');

  // Helper to detect if an object's metadata has been retrieved locally
  function isObjectRetrieved(objectApi) {
    const objDir = path.join(root, 'objects', objectApi);
    try {
      const stat = fs.statSync(objDir);
      return stat.isDirectory();
    } catch {
      return false;
    }
  }

  // Load all profiles content once
  let profileFiles = [];
  try {
    profileFiles = (await fsp.readdir(allProfilesDir))
      .filter(n => n.endsWith('.profile-meta.xml'))
      .map(n => path.join(allProfilesDir, n));
  } catch (e) {
    logv(verbose, 'Profiles directory not found or unreadable:', allProfilesDir);
  }
  const profileXmls = [];
  for (const pf of profileFiles) {
    const px = await readIfExists(pf);
    if (px != null) profileXmls.push(px);
  }

  const rows = [];
  const mdSections = [];
  const summaryLines = [];
  const missingLayoutsGlobal = new Set();

  for (const objectApi of objects) {
    logv(verbose, 'Processing object:', objectApi);

    // Detect if object metadata exists locally; if not, emit guidance and continue
    if (!isObjectRetrieved(objectApi)) {
      console.warn(`[sdcReport] Skipping ${objectApi}: object metadata folder not found at ${path.join(root, 'objects', objectApi)}.`);
      console.warn(`[sdcReport] Recommendation: retrieve the ${objectApi} object metadata and rerun. Example:`);
      console.warn(`  sf project retrieve start -m "CustomObject:${objectApi}"`);
      // Special handling for Task/Event record types — stored under Activity/recordTypes in source format
      if (objectApi === 'Task' || objectApi === 'Event') {
        console.warn(`[sdcReport] Note: ${objectApi} record types are stored under Activity in source format.`);
        console.warn(`  sf project retrieve start -m "RecordType:Activity.*,Layout:${objectApi}"`);
      }
      // Write empty detail files to keep structure predictable
      const objectDetailsDir = path.join(DETAILS_DIR, objectApi);
      await ensureDir(objectDetailsDir);
      await fsp.writeFile(path.join(objectDetailsDir, 'sdc-recordTypes.json'), '[]', 'utf8');
      await fsp.writeFile(path.join(objectDetailsDir, 'sdc-layouts.json'), JSON.stringify({ layouts: [], assignments: [] }, null, 2), 'utf8');
      await fsp.writeFile(path.join(objectDetailsDir, 'layout-fields.json'), '{}', 'utf8');
      await fsp.writeFile(path.join(objectDetailsDir, 'rules.json'), '[]', 'utf8');
      continue;
    }
    const objectDir = path.join(root, 'objects', objectApi);
    const vrDir = path.join(objectDir, 'validationRules');
    let rtDir = path.join(objectDir, 'recordTypes');

    // For Task and Event, record types live under Activity/recordTypes in source format.
    // If Task/Event itself has no recordTypes dir, fall back to Activity.
    if ((objectApi === 'Task' || objectApi === 'Event')) {
      const activityRtDir = path.join(root, 'objects', 'Activity', 'recordTypes');
      if (!fs.existsSync(rtDir) && fs.existsSync(activityRtDir)) {
        rtDir = activityRtDir;
        logv(verbose, `Using Activity recordTypes for ${objectApi}: ${activityRtDir}`);
      }
    }

    const objectDetailsDir = path.join(DETAILS_DIR, objectApi);
    await ensureDir(objectDetailsDir);

    // Record Types
    let rtFiles = [];
    try {
      rtFiles = (await fsp.readdir(rtDir))
        .filter(n => n.endsWith('.recordType-meta.xml'))
        .map(n => path.join(rtDir, n));
    } catch (e) {
      // no RTs
    }
    const recordTypes = [];
    for (const rf of rtFiles) {
      const x = await readIfExists(rf);
      if (!x) continue;
      const rt = parseRecordTypeXml(x);
      if (rt.fullName) recordTypes.push(rt);
    }
    // SDC RTs by API name rule (fullName starts with sdcPrefix)
    const sdcRTs = recordTypes.filter(rt => (rt.fullName || '').startsWith(sdcPrefix));
    if (verbose) {
      console.log(`[sdcReport] ${objectApi} record types found:`, recordTypes.map(r => r.fullName));
      console.log(`[sdcReport] ${objectApi} SDC record types (prefix ${sdcPrefix}):`, sdcRTs.map(r => r.fullName));
    }
    await fsp.writeFile(path.join(objectDetailsDir, 'sdc-recordTypes.json'), JSON.stringify(sdcRTs, null, 2), 'utf8');

    // Collect SDC layout assignments from profiles
    const sdcLayouts = new Set();
    const layoutAssignmentsDetail = []; // {profile, layout, recordType}
    if (sdcRTs.length > 0 && profileXmls.length > 0) {
      if (verbose) {
        console.log(`[sdcReport] ${objectApi} profiles scanned: ${profileFiles.length}`);
      }
      for (let i = 0; i < profileXmls.length; i++) {
        const pXml = profileXmls[i];
        // Extract Profile name for reporting
        const profileName = xmlTextBetween('fullName', pXml) || `Profile#${i+1}`;
        const assns = parseProfileLayoutAssignments(pXml, objectApi);
        if (verbose && assns.length > 0) {
          console.log(`[sdcReport] ${objectApi} profile ${profileName} layoutAssignments:`, assns);
        }
        for (const a of assns) {
          // recordType is of form 'ObjectApi.RecordTypeApi'
          if (a.recordType) {
            const parts = a.recordType.split('.');
            const rtApi = parts.length > 1 ? parts[1] : parts[0];
            const match = sdcRTs.find(rt => rt.fullName === rtApi);
            if (match) {
              sdcLayouts.add(a.layout);
              layoutAssignmentsDetail.push({ profile: profileName, layout: a.layout, recordType: a.recordType });
              if (verbose) {
                console.log(`[sdcReport] ${objectApi} matched SDC RT ${rtApi} -> layout ${a.layout} (profile ${profileName})`);
              }
            } else if (verbose) {
              console.log(`[sdcReport] ${objectApi} RT ${rtApi} is not SDC; skipping layout ${a.layout}`);
            }
          }
        }
      }
    }
    if (verbose) {
      console.log(`[sdcReport] ${objectApi} SDC layouts gathered:`, Array.from(sdcLayouts));
    }
    await fsp.writeFile(path.join(objectDetailsDir, 'sdc-layouts.json'), JSON.stringify({ layouts: Array.from(sdcLayouts), assignments: layoutAssignmentsDetail }, null, 2), 'utf8');

    // Extract fields present on SDC layouts
    const layoutFieldsMap = {}; // layoutName -> Set(fields) serialized as array
    const unionLayoutFields = new Set();
    for (const layoutName of sdcLayouts) {
      const layoutFile = path.join(layoutsDir, `${layoutName}.layout-meta.xml`);
      const lx = await readIfExists(layoutFile);
      if (!lx) {
        logv(verbose, `Missing layout file for ${layoutName}`);
        layoutFieldsMap[layoutName] = { missing: true, fields: [] };
        missingLayoutsGlobal.add(layoutName);
        continue;
      }
      const fset = parseLayoutFields(lx);
      if (verbose) {
        console.log(`[sdcReport] ${objectApi} parsed ${layoutName} fields count: ${fset.size}`);
      }
      layoutFieldsMap[layoutName] = { missing: false, fields: Array.from(fset) };
      for (const f of fset) unionLayoutFields.add(f);
    }
    await fsp.writeFile(path.join(objectDetailsDir, 'layout-fields.json'), JSON.stringify(layoutFieldsMap, null, 2), 'utf8');

    // Validation Rules
    let vrFiles = [];
    try {
      vrFiles = (await fsp.readdir(vrDir))
        .filter(n => n.endsWith('.validationRule-meta.xml'))
        .map(n => path.join(vrDir, n));
    } catch (e) {
      // none
    }

    const rulesDetails = [];
    for (const vf of vrFiles) {
      const vx = await readIfExists(vf);
      if (!vx) continue;
      const vr = parseValidationRuleXml(vx);
      if (!vr.fullName) continue;
      if (!includeInactive && !vr.active) continue;

      const parsedFields = Array.from(parseFieldsFromFormula(vr.errorConditionFormula, objectApi));

      // Relevance: intersection with unionLayoutFields (ANY layout)
      if (verbose) {
        console.log(`[sdcReport] ${objectApi} rule ${vr.fullName} parsed fields:`, parsedFields);
      }
      const matching = parsedFields.filter(f => unionLayoutFields.has(f));
      if (verbose) {
        console.log(`[sdcReport] ${objectApi} rule ${vr.fullName} matching fields on SDC layouts:`, matching);
      }
      const relevant = matching.length > 0 && sdcRTs.length > 0 && sdcLayouts.size > 0;

      // Which layouts contained these matching fields
      const matchingLayouts = new Set();
      if (matching.length > 0) {
        for (const [layoutName, rec] of Object.entries(layoutFieldsMap)) {
          if (rec.missing) continue;
          const layoutFieldSet = new Set(rec.fields);
          for (const mf of matching) {
            if (layoutFieldSet.has(mf)) {
              matchingLayouts.add(layoutName);
            }
          }
        }
      }

      rulesDetails.push({
        object: objectApi,
        ruleName: vr.fullName,
        active: vr.active,
        description: vr.description || '',
        formula: vr.errorConditionFormula || '',
        errorDisplayField: vr.errorDisplayField || '',
        referencedFields: parsedFields,
        sdcRecordTypes: sdcRTs.map(rt => rt.fullName),
        sdcLayouts: Array.from(sdcLayouts),
        relevant,
        matchingFields: matching,
        matchingLayouts: Array.from(matchingLayouts),
      });

      // CSV row
      rows.push([
        objectApi,
        vr.fullName,
        vr.active ? 'true' : 'false',
        (vr.description || '').replace(/\s+/g, ' ').trim(),
        parsedFields.join(';'),
        sdcRTs.map(rt => rt.fullName).join(';'),
        Array.from(sdcLayouts).join(';'),
        relevant ? 'Y' : 'N',
        matching.join(';'),
        Array.from(matchingLayouts).join(';'),
        (vr.errorConditionFormula || '').replace(/\s+/g, ' ').trim(),
      ]);
    }

    await fsp.writeFile(path.join(objectDetailsDir, 'rules.json'), JSON.stringify(rulesDetails, null, 2), 'utf8');

    // Markdown section per object
    const totalActive = rulesDetails.filter(r => r.active).length;
    const totalRelevant = rulesDetails.filter(r => r.active && r.relevant).length;
    summaryLines.push(`${objectApi}: ${totalRelevant}/${totalActive} relevant active rules`);
    const lines = [];
    lines.push(`## ${objectApi}`);
    if (sdcRTs.length === 0) {
      lines.push(`- No SDC record types (API name starts with "${sdcPrefix}") found for ${objectApi}.`);
    } else {
      lines.push(`- SDC Record Types (API): ${sdcRTs.map(rt => rt.fullName).join(', ')}`);
    }
    if (sdcLayouts.size === 0) {
      lines.push(`- No SDC layout assignments found across profiles for ${objectApi}.`);
    } else {
      lines.push(`- SDC Layouts checked: ${Array.from(sdcLayouts).join(', ')}`);
    }
    lines.push('');
    for (const r of rulesDetails) {
      if (!r.active) continue; // Only document active ones in MD by default
      lines.push(`- Rule: ${r.ruleName} | Relevant: ${r.relevant ? 'Y' : 'N'}`);
      if (r.description) lines.push(`  - Desc: ${r.description}`);
      lines.push(`  - Referenced Fields: ${r.referencedFields.join(', ') || '(none parsed)'}`);
      if (r.relevant) {
        lines.push(`  - Matching Fields: ${r.matchingFields.join(', ')}`);
        lines.push(`  - Matching Layouts: ${r.matchingLayouts.join(', ')}`);
      }
      lines.push(`  - Formula: ${r.formula ? '`' + r.formula.replace(/`/g, '\\`') + '`' : '(empty)'}`);
    }
    lines.push('');
    mdSections.push(lines.join('\n'));
  }

  // Write CSV
  const csvHeader = [
    'Object',
    'RuleName',
    'Active',
    'Description',
    'ReferencedFields',
    'SDC_RecordTypes',
    'SDC_Layouts_Checked',
    'Relevant',
    'MatchingFields',
    'MatchingLayouts',
    'Formula',
  ];
  const csvLines = [csvHeader.map(csvEscape).join(',')];
  for (const row of rows) {
    csvLines.push(row.map(csvEscape).join(','));
  }
  await fsp.writeFile(path.join('reports', 'sdc-validation-rules.csv'), csvLines.join('\n'), 'utf8');

  // Write MD
  const md = [
    '# SDC Validation Rule Relevance Report',
    '',
    `- Record type match: API Name starts with "${sdcPrefix}"`,
    '- Relevant if any referenced field is present on any SDC layout assignment across profiles',
    '',
    '## Summary',
    '',
    summaryLines.length ? summaryLines.map(s => `- ${s}`).join('\n') : '- No data',
    '',
    '## Details',
    '',
    mdSections.join('\n'),
  ].join('\n');

  await fsp.writeFile(path.join('reports', 'sdc-validation-rules.md'), md, 'utf8');

  console.log('Report generated:');
  console.log('- reports/sdc-validation-rules.csv');
  console.log('- reports/sdc-validation-rules.md');

  if (missingLayoutsGlobal.size > 0) {
    const list = Array.from(missingLayoutsGlobal).join(', ');
    console.warn('\nWarning: One or more SDC-assigned layouts referenced by profiles were not found in the local repository.\n' +
      'This prevents extracting fields and may under-report relevant validation rules.\n' +
      'Missing layouts:\n  - ' + list.split(', ').join('\n  - ') + '\n\n' +
      'Recommendation: retrieve Layout metadata from your org, then re-run this script.\n' +
      'Example:\n' +
      '  sf project retrieve start -m "Layout:Account,Layout:Lead,Layout:Contact,Layout:Opportunity,Layout:Campaign,Layout:User,Layout:Invoice__c,Layout:Task,Layout:Event"\n');
  }
}

main().catch(err => {
  console.error('Error generating SDC validation report:', err);
  process.exit(1);
});
