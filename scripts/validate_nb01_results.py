import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))
from src.ingest.excel_parser import parse_master_excel
from src.ingest.pdf_parser import parse_pdf_blocks

OUT = Path('data/output')
IN = Path('data/incoming')

nb01_file = OUT / 'nb01_4AllAnnexures_results.json'
if not nb01_file.exists():
    print('nb01 results not found:', nb01_file)
    raise SystemExit(1)

with open(nb01_file, 'r', encoding='utf-8') as f:
    results = json.load(f)

master = IN / 'Tech_Comp_check_list.xlsx'
if not master.exists():
    masters = sorted(IN.glob('*.xlsx'))
    master = masters[0] if masters else None
if not master:
    print('No master workbook found in data/incoming')
    raise SystemExit(1)

specs = parse_master_excel(str(master))
nb01_specs = {s['Spec_ID']: s for s in specs if (s.get('Spec_ID') or '').upper().startswith('NB01')}

vendor_pdf = IN.glob('*.pdf')
vendor_list = sorted(IN.glob('*.pdf'))
if not vendor_list:
    print('No vendor PDFs')
    raise SystemExit(1)
vendor = vendor_list[0]
blocks = parse_pdf_blocks(str(vendor))
pages = set(b['page'] for b in blocks)

# Map page->list of texts
page_texts = {}
for b in blocks:
    page_texts.setdefault(b['page'], []).append(b['text'])

# Validate
found_specs = set(r['spec_id'] for r in results)
expected_specs = set(nb01_specs.keys())
missing = expected_specs - found_specs
extra = found_specs - expected_specs

mismatches = []
for r in results:
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
        # check excerpt exists in any block on cited page (if page available)
        if page in page_texts:
            joined = '\n'.join(page_texts[page])
            if excerpt not in joined:
                # maybe excerpt truncated; check a small substring
                sub = excerpt[:50]
                if sub and sub not in joined:
                    issues.append('excerpt_not_found_on_page')
        else:
            issues.append('no_text_on_cited_page')
    if issues:
        mismatches.append({'spec_id': sid, 'issues': issues, 'citation_page': page})

# Summary
print('Master file:', master.name)
print('Vendor file:', vendor.name)
print('NB01 specs expected:', len(expected_specs))
print('NB01 results found:', len(results))
print('Missing spec results (present in master, not in output):', sorted(list(missing))[:10])
print('Extra spec results (present in output, not in master):', sorted(list(extra))[:10])
print('Mismatches count:', len(mismatches))
if mismatches:
    print('\nSample mismatches (up to 20):')
    for m in mismatches[:20]:
        print('-', m)

# Exit code non-zero if critical issues
critical = [m for m in mismatches if any(i.startswith('citation_page_missing') for i in m['issues'])]
if missing or critical:
    print('\nValidation FAILED: missing results or critical citation issues')
    raise SystemExit(2)
else:
    print('\nValidation OK: NB01 results present and citations roughly match incoming PDF pages')
    sys.exit(0)
