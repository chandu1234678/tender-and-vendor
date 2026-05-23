import json
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))
from src.ingest.excel_parser import parse_master_excel

OUT = Path('data/output')
IN = Path('data/incoming')
refined_file = OUT / 'nb01_4AllAnnexures_results_refined.json'
if not refined_file.exists():
    refined_file = OUT / 'nb01_4AllAnnexures_results.json'
    if not refined_file.exists():
        print('No NB01 results found to reason about')
        raise SystemExit(1)

with open(refined_file, 'r', encoding='utf-8') as f:
    results = json.load(f)

master = IN / 'Tech_Comp_check_list.xlsx'
if not master.exists():
    masters = sorted(IN.glob('*.xlsx'))
    master = masters[0] if masters else None
if not master:
    print('Master not found')
    raise SystemExit(1)

specs = parse_master_excel(str(master))
spec_map = {s['Spec_ID']: s for s in specs}

TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)

def tokenize(text):
    return [t.lower() for t in TOKEN_RE.findall((text or '')) if len(t) > 1]

reasoned = []
counts = {'YES':0,'NO':0,'NEARLY OK':0,'OTHER':0}
for r in results:
    sid = r.get('spec_id')
    spec = spec_map.get(sid, {})
    requirement = spec.get('BHEL_Requirement') or spec.get('company_Requirement') or spec.get('company_requirement') or ''
    excerpt = (r.get('citation') or '').strip()
    page = r.get('citation_page')
    status = (r.get('status') or '').upper()
    conf = float(r.get('confidence') or 0.0)

    spec_tokens = set(tokenize(requirement))
    excerpt_tokens = set(tokenize(excerpt))
    overlap = spec_tokens & excerpt_tokens
    overlap_pct = (len(overlap) / max(1, len(spec_tokens))) if spec_tokens else 0.0

    if status == 'YES' or conf >= 0.9:
        reason = (
            f"Requirement appears satisfied. Citation (page {page}): '{excerpt[:200]}'. "
            f"Token overlap {len(overlap)} of {len(spec_tokens)} ({overlap_pct:.0%})."
        )
        counts['YES'] += 1
    elif status == 'NEARLY OK' or (0.5 <= conf < 0.9) or (0.15 <= overlap_pct < 0.5):
        reason = (
            f"Partial match found. Citation (page {page}): '{excerpt[:200]}'. "
            f"This matches some parts of the requirement but may miss explicit wording—token overlap {len(overlap)} of {len(spec_tokens)} ({overlap_pct:.0%}). "
            f"Consider manual review or running the model for full verification."
        )
        counts['NEARLY OK'] += 1
    else:
        reason = (
            f"No clear match for requirement. Top citation (page {page}): '{excerpt[:200]}'. "
            f"Token overlap {len(overlap)} of {len(spec_tokens)} ({overlap_pct:.0%}), so heuristic indicates non-compliance. "
            f"Recommend manual review or full model check."
        )
        counts['NO'] += 1

    # ensure reasoning field is updated
    r['reasoning'] = reason
    reasoned.append(r)

# write out
out_file = OUT / 'nb01_4AllAnnexures_results_reasoned.json'
with open(out_file, 'w', encoding='utf-8') as f:
    json.dump(reasoned, f, ensure_ascii=False, indent=2)

print('Wrote reasoned results to', out_file)
print('Summary counts:', counts)
