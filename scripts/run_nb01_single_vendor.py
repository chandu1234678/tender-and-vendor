import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path.cwd()))

from src.utils.logging import setup_logging
from src.ingest.excel_parser import parse_master_excel
from src.ingest.pdf_parser import parse_pdf_blocks
from src.engine.orchestrator import dispatch_spec_vendor

setup_logging()

cfg_in = Path('data/incoming')
master = cfg_in / 'Tech_Comp_check_list.xlsx'
if not master.exists():
    masters = sorted(cfg_in.glob('*.xlsx'))
    master = masters[0] if masters else None
if not master:
    print('No master workbook found in data/incoming')
    raise SystemExit(1)

specs = parse_master_excel(str(master))
filtered = [s for s in specs if (s.get('Spec_ID') or '').upper().startswith('NB01')]
if not filtered:
    print('No NB01 specs found in master')
    raise SystemExit(1)

vendors = sorted(cfg_in.glob('*.pdf'))
if not vendors:
    print('No vendor PDFs found in data/incoming')
    raise SystemExit(1)

vendor = vendors[0]
vendor_id = vendor.stem
print(f'Using master: {master.name}, vendor: {vendor.name} (vendor_id={vendor_id}), specs: {len(filtered)}')

blocks = parse_pdf_blocks(str(vendor))

results = []
for spec in filtered:
    try:
        print(f'Processing spec {spec.get("Spec_ID")}...')
        # use very-fast heuristic mode to avoid model calls
        result = dispatch_spec_vendor(spec, vendor_id, blocks, top_k=1, agents=[], fast=True)
        out = {
            'spec_id': result.get('spec_id'),
            'vendor_id': result.get('vendor_id'),
            'status': result.get('status'),
            'confidence': result.get('confidence'),
            'citation_page': result.get('citation_page'),
            'citation_excerpt': (result.get('citation') or '')[:300],
        }
        results.append(out)
        print(json.dumps(out, ensure_ascii=False))
    except Exception as e:
        print(f'Error processing {spec.get("Spec_ID")} : {e}')

out_path = Path('data/output')
out_path.mkdir(parents=True, exist_ok=True)
with open(out_path / f'nb01_{vendor_id}_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f'Wrote {len(results)} results to {out_path / f"nb01_{vendor_id}_results.json"}')
