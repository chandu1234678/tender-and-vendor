import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from src.ingest.excel_parser import parse_master_excel
from src.ingest.pdf_parser import parse_pdf_blocks
from src.engine.orchestrator import dispatch_spec_vendor

IN = Path('data/incoming')
OUT = Path('data/output')
orig = OUT / 'nb01_4AllAnnexures_results.json'
if not orig.exists():
    print('Original NB01 results not found:', orig)
    raise SystemExit(1)

with open(orig, 'r', encoding='utf-8') as f:
    results = json.load(f)

# load master and specs
master = IN / 'Tech_Comp_check_list.xlsx'
if not master.exists():
    masters = sorted(IN.glob('*.xlsx'))
    master = masters[0] if masters else None
if not master:
    print('Master not found')
    raise SystemExit(1)
specs = parse_master_excel(str(master))
spec_map = {s['Spec_ID']: s for s in specs}

# load vendor blocks
vendors = sorted(IN.glob('*.pdf'))
if not vendors:
    print('No vendor PDFs')
    raise SystemExit(1)
vendor = vendors[0]
vendor_id = vendor.stem
blocks = parse_pdf_blocks(str(vendor))

# identify uncertain results
THRESH = 0.95
uncertain = [r for r in results if (r.get('confidence') is None) or (float(r.get('confidence',0.0)) < THRESH)]
print(f'Total results: {len(results)}, uncertain (<{THRESH}): {len(uncertain)}')
if not uncertain:
    print('No uncertain results to refine; exiting')
    raise SystemExit(0)

refined = {r['spec_id']: r for r in results}
# sequentially re-run model-based dispatch for uncertain specs
for i, r in enumerate(uncertain, start=1):
    sid = r.get('spec_id')
    print(f'[{i}/{len(uncertain)}] Refining {sid}...')
    spec = spec_map.get(sid)
    if not spec:
        print('  Spec not found in master:', sid)
        continue
    try:
        # call model-based check (top_k=3, default agents -> runs technical+risk+fallback)
        res = dispatch_spec_vendor(spec, vendor_id, blocks, top_k=3, fast=False)
        # update refined
        refined[sid] = res
        print('  -> refined status:', res.get('status'), 'confidence:', res.get('confidence'))
    except Exception as e:
        print('  Error refining', sid, e)
    # small pause to avoid overwhelming local server
    time.sleep(0.35)

# write refined results
out_file = OUT / 'nb01_4AllAnnexures_results_refined.json'
with open(out_file, 'w', encoding='utf-8') as f:
    json.dump(list(refined.values()), f, ensure_ascii=False, indent=2)

print('Refined results written to', out_file)

# Run same validation logic inline
from src.ingest.excel_parser import parse_master_excel

specs = parse_master_excel(str(master))
nb01_specs = {s['Spec_ID']: s for s in specs if (s.get('Spec_ID') or '').upper().startswith('NB01')}
pages = set(b['page'] for b in blocks)
page_texts = {}
for b in blocks:
    page_texts.setdefault(b['page'], []).append(b['text'])

found_specs = set(r['spec_id'] for r in refined.values())
expected_specs = set(nb01_specs.keys())
missing = expected_specs - found_specs
extra = found_specs - expected_specs
mismatches = []
for r in refined.values():
    sid = r.get('spec_id')
    conf = r.get('confidence')
    page = r.get('citation_page')
    excerpt = (r.get('citation') or '').strip()
    issues = []
    if sid not in nb01_specs:
        issues.append('spec_not_in_master')
    if conf is None or not (0.0 <= float(conf) <= 1.0):
        issues.append('confidence_out_of_range')
    if page is not None and page not in pages:
        issues.append(f'citation_page_missing:{page}')
    if excerpt:
        if page in page_texts:
            joined = '\n'.join(page_texts[page])
            if excerpt not in joined:
                sub = excerpt[:50]
                if sub and sub not in joined:
                    issues.append('excerpt_not_found_on_page')
        else:
            issues.append('no_text_on_cited_page')
    if issues:
        mismatches.append({'spec_id': sid, 'issues': issues, 'citation_page': page})

print('\nValidation summary after refinement:')
print('Expected NB01 specs:', len(expected_specs))
print('Refined results:', len(refined))
print('Missing:', sorted(list(missing))[:10])
print('Extra:', sorted(list(extra))[:10])
print('Mismatches:', len(mismatches))
if mismatches:
    print('Sample mismatches:', mismatches[:10])

if missing or any('citation_page_missing' in ';'.join(m['issues']) for m in mismatches):
    print('Validation FAILED after refinement')
    raise SystemExit(2)
else:
    print('Validation OK after refinement')
    sys.exit(0)
