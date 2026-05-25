# Tender-Vendor Matching Report

Generated: 2026-05-25T11:55:24.511000

## Summary
- Master spec rows: 6,397
- Vendors matched: 2
- Rows evaluated per vendor: 520
- Coverage per vendor: 8.13% (520 / 6,397)
- Citation coverage: 100% (all evaluated rows have `citation_page`)

## Per-Vendor Status Counts
- 4AllAnnexures: YES=480, NEARLY OK=1, NO=39
- Alstonia-merged: YES=480, NEARLY OK=1, NO=39

## Output Files
- data/output/vendor_comparison_matrix.xlsx
- data/output/vendor_4AllAnnexures.xlsx
- data/output/vendor_Alstonia-merged.xlsx

## Notes on "Accuracy"
There is no ground-truth label set in the database. The accuracy proxy used here is:
- Coverage: how many tender rows were evaluated vs. total master specs
- Citation completeness: % of evaluated rows with a page number

If you want a true accuracy score, provide a labeled sample (expected YES/NO/NEARLY OK per spec) and I will add a validation pass.
