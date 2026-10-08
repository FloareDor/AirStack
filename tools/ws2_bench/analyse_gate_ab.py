"""Aggregate the gate A/B across repeat chunks and say what it does not show.

run_gate_validation.py writes one directory per chunk. Reading them together is
the only way to compare arms, because a single flight per arm cannot separate a
gate effect from run-to-run variation: on 2026-10-08 two of three saved
collision scenarios reached the goal when replayed, so a lone 'it did not crash'
means nothing.

Outcomes are read from each run's result.json rather than from summary.json,
whose outcome column was wrong before the parser fix.
"""
import argparse,json,statistics
from pathlib import Path

SUCCESSES={'goal_reached','completed_horizon'}

def flights(roots):
    rows=[]
    for root in roots:
        for d in sorted(p for p in Path(root).iterdir() if p.is_dir()):
            f=d/'result.json'
            if not f.exists():continue
            parts=d.name.split('__')
            if len(parts)!=3:continue
            case,arm,_=parts
            r=json.loads(f.read_text());m=r.get('metrics') or {}
            rows.append({'chunk':Path(root).name,'case':case,'arm':arm,'outcome':r['outcome'],
                         'progress':m.get('mission_progress_percent'),'path_m':m.get('path_length_m'),
                         'clearance_m':m.get('minimum_obstacle_clearance_m'),
                         'recoveries':m.get('planner_recovery_count')})
    return rows

def summarise(rows):
    arms=sorted({r['arm'] for r in rows});cases=sorted({r['case'] for r in rows})
    out={'per_arm':{},'per_case':{},'infrastructure_errors':sum(r['outcome']=='infrastructure_error' for r in rows),
         'flights':len(rows)}
    for arm in arms:
        sel=[r for r in rows if r['arm']==arm and r['outcome']!='infrastructure_error']
        prog=[r['progress'] for r in sel if isinstance(r['progress'],(int,float))]
        out['per_arm'][arm]={'n':len(sel),
            'goal':sum(r['outcome'] in SUCCESSES for r in sel),
            'collision':sum(r['outcome']=='collision' for r in sel),
            'planner_stopped':sum(r['outcome']=='planner_stopped' for r in sel),
            'median_progress_percent':round(statistics.median(prog),2) if prog else None}
    for case in cases:
        out['per_case'][case]={arm:[r['outcome'] for r in rows if r['case']==case and r['arm']==arm] for arm in arms}
    return out

def verdict(s):
    arms=list(s['per_arm'])
    if s['infrastructure_errors']:
        return (f"{s['infrastructure_errors']} of {s['flights']} flights were infrastructure errors; "
                "fix the workspace before reading the comparison.")
    if len(arms)!=2:return 'Need exactly two arms to compare.'
    a,b=arms;A,B=s['per_arm'][a],s['per_arm'][b]
    if A['n']==0 or B['n']==0:return 'An arm has no valid flights.'
    # A gate that stops everything trivially avoids every collision, so a lower
    # collision count only means something if the arm still flies.
    grounded=[k for k in (a,b) if (s['per_arm'][k]['median_progress_percent'] or 0)<10]
    if grounded:
        return (f"{' and '.join(grounded)} barely moved (median progress under 10 percent), so any "
                "avoided collision in that arm is explained by not flying, not by detection.")
    if A['collision']==B['collision']:
        return (f"Both arms collided {A['collision']} times in {A['n']} and {B['n']} flights. "
                "This run shows no difference between the arms, which with this sample means the "
                "gate was not exercised, not that it works.")
    return (f"{a}: {A['collision']}/{A['n']} collisions, {b}: {B['collision']}/{B['n']}. "
            "A difference this small at this sample size is not significant; treat it as a lead.")

def main():
    p=argparse.ArgumentParser()
    p.add_argument('roots',nargs='+',type=Path)
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    rows=flights(a.roots);s=summarise(rows);s['verdict']=verdict(s)
    for r in rows:
        print('%-14s %-24s %-14s %-20s prog=%s path=%s'%(r['chunk'],r['case'],r['arm'],r['outcome'],
              None if r['progress'] is None else round(r['progress'],1),
              None if r['path_m'] is None else round(r['path_m'],2)))
    print();print(json.dumps({k:v for k,v in s.items() if k!='per_case'},indent=2))
    print();print('VERDICT:',s['verdict'])
    if a.output:a.output.write_text(json.dumps({'flights':rows,**s},indent=2))

if __name__=='__main__':main()
