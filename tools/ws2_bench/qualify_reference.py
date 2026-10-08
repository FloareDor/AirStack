"""Fly the registered reference condition until it has two clean successes.

compare_policies.py refuses to start a study without a qualification.json
holding two independent successful clean flights at exactly the reference
condition, but nothing committed produced that file. This does.

The condition is expanded_space.reference_action(): generated seed42, easy
density, 0.9m corridor half-width, no side bias, light 1800, and no delay,
noise or patch. Each flight gets its own directory so the independence check
in compare_policies.run_study passes.
"""
import argparse,json,subprocess,sys
from pathlib import Path

from audit_results import audit_episode
from episode import RUNTIME,resolved
from expanded_space import action_to_episode,reference_action
from mission import SUCCESSES,defaults

HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--successes',type=int,default=2,help='clean successes required')
    p.add_argument('--attempts',type=int,default=4,help='give up after this many flights')
    a=p.parse_args()
    root=Path(a.output).resolve();root.relative_to(RUNTIME.resolve());root.mkdir(parents=True,exist_ok=True)
    import yaml
    scenario=resolved(action_to_episode(reference_action(),'mononav',42,'reference',defaults('mononav')))
    values=[]
    for attempt in range(a.attempts):
        if len(values)>=a.successes:break
        run=root/f'flight_{attempt:02d}'
        path=root/f'flight_{attempt:02d}.yaml'
        path.write_text(yaml.safe_dump(scenario,sort_keys=False))
        print(f'=== {run.name}',flush=True)
        r=subprocess.run([sys.executable,str(HERE/'episode.py'),str(path),'--output',str(run)],
                         stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (root/f'{run.name}.log').write_text(r.stdout)
        result=json.loads((run/'result.json').read_text())
        audit=audit_episode(run)
        print(f"    {result['outcome']}  audit_passed={audit['passed']}",flush=True)
        if result['outcome'] in SUCCESSES and audit['passed']:
            values.append({'result_dir':str(run),'outcome':result['outcome'],
                           'configuration_hash':result['configuration_hash']})
        (root/'qualification.json').write_text(json.dumps(values,indent=2))
    print(json.dumps(values,indent=2))
    if len(values)<a.successes:
        print(f'FAILED: {len(values)}/{a.successes} clean successes',flush=True);sys.exit(1)

if __name__=='__main__':main()
