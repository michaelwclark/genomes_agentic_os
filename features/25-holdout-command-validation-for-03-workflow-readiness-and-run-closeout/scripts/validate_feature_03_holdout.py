#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, sys, tempfile
from pathlib import Path

def run(cmd, cwd, expect=0):
    p=subprocess.run(cmd,cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    if p.returncode!=expect: raise AssertionError(f"command returned {p.returncode}, expected {expect}: {' '.join(cmd)}\n{p.stdout}")
    return p.stdout

def require(cond,msg):
    if not cond: raise AssertionError(msg)

def validate(repo: Path):
    with tempfile.TemporaryDirectory(prefix='agentic-os-feature-03-') as tmp:
        root=Path(tmp)/'agentic_os'
        run(['uv','run','agentic-os','init','--target',str(root)], repo)
        run(['uv','run','agentic-os','project','create','los','losmon_replacement','--root',str(root)], repo)
        run(['uv','run','agentic-os','workflow','create','los','engineering','feature_dev','--root',str(root)], repo)
        check=run(['uv','run','agentic-os','workflow','check','los','engineering','feature_dev','--root',str(root)], repo)
        require('fix-soon' in check or 'observation' in check, 'workflow check did not emit expected severity')
        run(['uv','run','agentic-os','run-log','create','los','feature_dev','--root',str(root)], repo)
        run_dir=next((root/'los'/'06-runs-and-logs'/'runs').glob('*-los-feature_dev'))
        run(['uv','run','agentic-os','run-log','close','los',run_dir.name,'--status','done','--root',str(root)], repo, expect=2)
        run(['uv','run','agentic-os','run-log','close','los',run_dir.name,'--status','done','--summary','Built and verified closeout.','--validation','holdout validation passed','--artifact','run-log.md','--approval','none','--next-action','continue','--learning','validation required for done','--project','losmon_replacement','--root',str(root)], repo)
        log=(run_dir/'run-log.md').read_text(); require('## Closeout' in log and 'holdout validation passed' in log, 'closeout missing run-log evidence')
        require(run_dir.name in (root/'los'/'06-runs-and-logs'/'activity-log.md').read_text(), 'activity log missing run id')
        require(run_dir.name in (root/'los'/'03-workflows'/'engineering'/'feature_dev'/'progress.md').read_text(), 'workflow progress missing run id')
        require('## Run Closeout' in (root/'los'/'02-projects'/'losmon_replacement'/'status.md').read_text(), 'project status missing closeout')
        run(['uv','run','agentic-os','validate','--root',str(root)], repo)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--repo',default='.'); args=ap.parse_args()
    try: validate(Path(args.repo).resolve())
    except AssertionError as e: print(f'feature 03 holdout validation failed: {e}', file=sys.stderr); return 1
    print('feature 03 holdout validation passed'); return 0
if __name__=='__main__': raise SystemExit(main())
