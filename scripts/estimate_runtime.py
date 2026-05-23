from pathlib import Path
import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P.cwd()))
from src.ingest.excel_parser import parse_master_excel

cfg_in = Path('data/incoming')
master = cfg_in / 'Tech_Comp_check_list.xlsx'
if not master.exists():
    masters = sorted(cfg_in.glob('*.xlsx'))
    master = masters[0] if masters else None
if not master:
    print('NO_MASTER')
    raise SystemExit(1)

specs = parse_master_excel(str(master))
vendors = sorted(cfg_in.glob('*.pdf'))
num_specs = len(specs)
num_vendors = len(vendors) or 0
pairs = max(1, num_specs * max(1, num_vendors))
# Observed average per pair (seconds)
avg_seconds = 45.0

total_seconds = pairs * avg_seconds
hrs = int(total_seconds // 3600)
mins = int((total_seconds % 3600) // 60)
secs = int(total_seconds % 60)

print('Master:', master.name)
print('Specs:', num_specs)
print('Vendors:', num_vendors)
print('Pairs:', pairs)
print(f'Estimated total runtime: {hrs}h {mins}m {secs}s (avg {avg_seconds}s per pair)')
print('\nIf you want a faster run: reduce concurrency, use a smaller model, or run on a machine with GPU.')