import json
from pathlib import Path
from analyse_gate_ab import flights,summarise,verdict

def run(root,case,arm,outcome,progress,path=5.):
    d=root/('%s__%s__00'%(case,arm));d.mkdir(parents=True,exist_ok=True)
    (d/'result.json').write_text(json.dumps({'outcome':outcome,'metrics':{
        'mission_progress_percent':progress,'path_length_m':path,
        'minimum_obstacle_clearance_m':.05,'planner_recovery_count':0}}))

def test_a_grounded_arm_is_not_credited_with_avoiding_collisions(tmp_path):
    r=tmp_path/'c1'
    for case in ('a','b','c'):
        run(r,case,'on','planner_stopped',0.,.27)
    run(r,'a','off','collision',22.)
    run(r,'b','off','goal_reached',94.)
    run(r,'c','off','goal_reached',94.)
    s=summarise(flights([r]));s['verdict']=verdict(s)
    assert s['per_arm']['on']['collision']==0
    assert 'explained by not flying' in s['verdict']

def test_no_difference_is_reported_as_unexercised_not_as_working(tmp_path):
    r=tmp_path/'c1'
    for arm in ('on','off'):
        for case in ('a','b','c'):
            run(r,case,arm,'goal_reached',94.)
    s=summarise(flights([r]));s['verdict']=verdict(s)
    assert 'not exercised' in s['verdict'] and 'not that it works' in s['verdict']

def test_infrastructure_errors_block_the_comparison(tmp_path):
    r=tmp_path/'c1'
    run(r,'a','on','infrastructure_error',0.,0.)
    run(r,'a','off','goal_reached',94.)
    s=summarise(flights([r]));s['verdict']=verdict(s)
    assert 'fix the workspace' in s['verdict']

def test_chunks_are_pooled(tmp_path):
    roots=[]
    for i in (1,2):
        r=tmp_path/('c%d'%i);roots.append(r)
        for arm in ('on','off'):run(r,'a',arm,'goal_reached',94.)
    s=summarise(flights(roots))
    assert s['flights']==4 and s['per_arm']['on']['n']==2
