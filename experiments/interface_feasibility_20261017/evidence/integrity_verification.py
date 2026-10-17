"""Copy of the actual byte-check algorithm; invoke from repository root.

The initial run used /private/tmp/package_zjj_evidence.py with equivalent logic
and wrote integrity.json. This portable copy prints JSON to stdout.
"""
import json
import subprocess
from pathlib import Path
root=Path.cwd()
base='cc4e36b4e302fcdc53cc809a012c77d8464182af'
files=subprocess.check_output(['git','ls-tree','-r','--name-only',base],text=True).splitlines()
changed=[f for f in files if (root/f).read_bytes()!=subprocess.check_output(['git','show',base+':'+f])]
print(json.dumps({'baseline':base,'tracked_files_checked':len(files),'changed_original_files':changed},indent=2))
raise SystemExit(bool(changed))
