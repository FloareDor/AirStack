"""Fly the three saved collision scenarios with the depth gates on and off.

The 2026-10-01 replay showed all three stopping safely with the fix in, but a
replay path diverges, so "it did not crash this time" does not by itself show
the gates caused it. Flying the same scenario both ways in one workspace is the
comparison that does: gates off is the code that collided, gates on is the fix.

Gates off means max_unmapped_gap=0 and zoe_degenerate_min_correspondence=0,
which is exactly the pre-fix scoring of unreadable depth and unmapped space.
"""
import argparse,datetime,json,subprocess,sys
from pathlib import Path
import yaml

HERE=Path(__file__).resolve().parent
CASES=['finding1_agent_round3','finding1_random_round2','finding2_easy0']
# Only the degenerate-depth gate is compared. The unmapped-gap gate is held at
# 0 in both arms because the first run of this script showed it grounds the
# planner: it rejects open space for being open, so an arm with it on measures
# that, not the depth fix. See mission.defaults('mononav').
ARMS={'zoe_gate_on':{'max_unmapped_gap':0.,'zoe_degenerate_min_correspondence':.12},
      'zoe_gate_off':{'max_unmapped_gap':0.,'zoe_degenerate_min_correspondence':0.}}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    # One flight per arm cannot separate the fix from run-to-run variation:
    # these scenarios do not reproduce their own collisions every time, which
    # is the weakness this comparison exists to remove.
    p.add_argument('--repeats',type=int,default=3)
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    rows=[]
    for case in CASES:
        base=yaml.safe_load((HERE/'artifacts'/'ws2_fix_validation'/case/'scenario.yaml').read_text())
        for arm,gates in ARMS.items():
            for i in range(a.repeats):
                run=a.output/f'{case}__{arm}__{i:02d}'
                scenario=dict(base,**gates)
                scenario['name']=f'{case} {arm}'
                path=a.output/f'{case}__{arm}__{i:02d}.yaml'
                path.write_text(yaml.safe_dump(scenario,sort_keys=False))
                print(f'=== {run.name}',flush=True)
                r=subprocess.run([sys.executable,str(HERE/'episode.py'),str(path),'--output',str(run)],
                                 stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                (a.output/f'{run.name}.log').write_text(r.stdout)
                # The episode writes its own result; stdout is not a parseable
                # frame. Scanning stdout for the last '{' lands inside a nested
                # object, so every flight was labelled episode_failed while the
                # saved result said otherwise.
                outcome='episode_failed'
                try:outcome=json.loads((run/'result.json').read_text()).get('outcome','unknown')
                except Exception:pass
                rows.append({'case':case,'arm':arm,'repeat':i,'outcome':outcome,'exit':r.returncode})
                print(f'    {outcome}',flush=True)
                (a.output/'summary.json').write_text(json.dumps(rows,indent=2))
    print(json.dumps(rows,indent=2))

if __name__=='__main__':main()
