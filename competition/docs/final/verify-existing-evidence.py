"""Run from repository root. Read-only verification, new report paths only."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from competition.verify_w_slice import verify

for folder, pin, count, filename in (
    ('w-slice-20261011-final', '65ee659c9636cf41e2de8647b5c49005d762cdf3074bc2e65ac6579952df0eda', 22,
     'protocol-final-20261011-w-verification.json'),
    ('w-same-oid-20261011', 'ab853d979c9853a966c7f771070115b82ab3dd62f4e8507168ba49f5110eb640', 3,
     'protocol-final-20261011-same-oid-verification.json'),
):
    result = verify(ROOT / 'competition/evidence' / folder,
                    expected_root_manifest=pin, expected_case_count=count, historical_source=True)
    (ROOT / 'competition/evidence' / ('cleanup-' + filename)).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
