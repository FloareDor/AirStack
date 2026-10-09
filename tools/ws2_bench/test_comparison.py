import json
from pathlib import Path
from compare_policies import method_result,report_study
from expanded_space import reference_action
from dashboard import adaptive_command

def write(root,name,value):
    root.mkdir(parents=True,exist_ok=True);(root/name).write_text(json.dumps(value))

def history(clean='goal_reached',attack='collision'):
    return [{'decision':{'round':i,'action':reference_action()},'pairs':[{
        role:{'outcome':outcome,'metrics':{},'wall_duration_s':2.} for role,outcome in [('clean',clean),('perturbed',attack)]}]} for i in (1,2)]

def test_clean_failures_and_infrastructure_are_not_agent_successes(tmp_path):
    root=tmp_path/'random';write(root,'history.json',history('collision','collision'))
    result=method_result(root)
    assert result['clean_failure_pairs']==2 and result['distinct_candidate_conditions']==0
    write(root,'history.json',history('infrastructure_error','infrastructure_error'))
    result=method_result(root)
    assert result['infrastructure_errors']==4 and result['evaluated_pairs']==0

def test_comparison_counts_repeat_once_and_does_not_invent_advantage(tmp_path):
    protocol={'order':['random','search','agent_search'],'flights_per_method':4,'qualification_directories':['test-reference']}
    write(tmp_path,'protocol.json',protocol)
    for name in protocol['order']:
        write(tmp_path/name,'config.json',{});write(tmp_path/name,'history.json',history())
    report=report_study(tmp_path)
    assert report['comparison_valid']
    assert all(r['distinct_candidate_conditions']==r['reproduced_conditions']==1 for r in report['results'])
    assert 'did not show a higher' in report['conclusion']
    assert all(r['flights_to_first_candidate']==2 for r in report['results'])

def test_expanded_viewer_needs_no_saved_layout_selector(tmp_path):
    cmd=adaptive_command({'planner':'mononav','policy':'random','action_space':'expanded','budget':4},tmp_path)
    assert cmd[cmd.index('--action-space')+1]=='expanded'
    assert '--qualified-layout' not in cmd

def test_llm_evidence_does_not_assign_kim_controls_to_mononav():
    from vulnerability_report import analyze
    from agent_analysis import evidence_for_report
    from mission import defaults
    for planner in ('mononav','kim'):
        evidence=evidence_for_report(analyze([],[],{'planners':[planner],'mission':defaults(planner)},'complete'))
        if planner=='mononav':
            assert 'maximum_speed' not in evidence['mission']
            assert 'governor' not in ' '.join(evidence['limitations'])
        else:
            assert 'velocity' not in evidence['mission']
            assert 'depth-based speed governor' in ' '.join(evidence['limitations'])
        assert 'does not establish' in evidence['parameter_definitions']['attack_effect_evaluable']


def passing_history(clean_clearance,attacked_clearance):
    return [{'decision':{'round':i,'action':reference_action()},'pairs':[{
        role:{'outcome':'goal_reached','wall_duration_s':2.,
              'metrics':{'minimum_obstacle_clearance_m':clearance}}
        for role,clearance in [('clean',clean_clearance),('perturbed',attacked_clearance)]}]} for i in (1,2)]

def test_clearance_loss_is_measured_per_pair(tmp_path):
    root=tmp_path/'random';write(root,'history.json',passing_history(.56,.29))
    result=method_result(root)
    assert result['attack_failure_pairs_with_clean_pass']==0
    assert result['median_clearance_loss_m']==.27 and result['clearance_pairs']==2
    assert result['worst_attacked_clearance_m']==.29

def test_a_pilot_with_no_failure_is_ranked_on_clearance_loss(tmp_path):
    protocol={'order':['random','search','agent_search'],'flights_per_method':4,'qualification_directories':['test-reference']}
    write(tmp_path,'protocol.json',protocol)
    losses={'random':.50,'search':.45,'agent_search':.20}
    for name,attacked in losses.items():
        write(tmp_path/name,'config.json',{});write(tmp_path/name,'history.json',passing_history(.6,attacked))
    report=report_study(tmp_path)
    assert report['comparison_valid']
    assert all(r['distinct_candidate_conditions']==0 for r in report['results'])
    # The widest paired loss wins, and the text must not call it a failure.
    assert 'agent_search removed the most clearance' in report['conclusion']
    assert 'cannot establish significance' in report['conclusion']

def test_clearance_columns_tolerate_a_run_without_metrics(tmp_path):
    root=tmp_path/'random';write(root,'history.json',history())
    result=method_result(root)
    assert result['median_clearance_loss_m'] is None and result['clearance_pairs']==0


def envelope_history(clean_env,attacked_env,basis='sphere_minus_envelope'):
    return [{'decision':{'round':i,'action':reference_action()},'pairs':[{
        role:{'outcome':'goal_reached','wall_duration_s':2.,
              'metrics':{'minimum_obstacle_clearance_m':.05,'clearance_envelope_m':env,
                         'clearance_basis':basis}}
        for role,env in [('clean',clean_env),('perturbed',attacked_env)]}]} for i in (1,2)]

def test_mixed_clearance_envelopes_are_flagged(tmp_path):
    protocol={'order':['random','search','agent_search'],'flights_per_method':4,'qualification_directories':['t']}
    write(tmp_path,'protocol.json',protocol)
    for name,env in [('random',.25),('search',.3482),('agent_search',.3482)]:
        write(tmp_path/name,'config.json',{});write(tmp_path/name,'history.json',envelope_history(env,env))
    report=report_study(tmp_path)
    assert report['mixed_clearance_envelopes']
    assert report['clearance_envelopes_m']==[.25,.3482]
    assert any('measured differently' in s for s in report['limitations'])

def test_mixed_clearance_bases_are_flagged(tmp_path):
    # The box basis reports the same measured hull as the scalar basis it
    # replaced, so the envelope alone cannot tell them apart. Pooling them
    # would compare a hull-to-surface distance against that distance minus the
    # hull diagonal.
    protocol={'order':['random','search','agent_search'],'flights_per_method':4,'qualification_directories':['t']}
    write(tmp_path,'protocol.json',protocol)
    for name,basis in [('random','sphere_minus_envelope'),('search','oriented_box'),('agent_search','oriented_box')]:
        write(tmp_path/name,'config.json',{})
        write(tmp_path/name,'history.json',envelope_history(.3482,.3482,basis))
    report=report_study(tmp_path)
    assert report['clearance_envelopes_m']==[.3482]
    assert report['clearance_bases']==['oriented_box','sphere_minus_envelope']
    assert report['mixed_clearance_envelopes']
    assert any('measured differently' in s for s in report['limitations'])

def test_one_basis_is_not_flagged(tmp_path):
    protocol={'order':['random','search','agent_search'],'flights_per_method':4,'qualification_directories':['t']}
    write(tmp_path,'protocol.json',protocol)
    for name in ('random','search','agent_search'):
        write(tmp_path/name,'config.json',{})
        write(tmp_path/name,'history.json',envelope_history(.3482,.3482,'oriented_box'))
    report=report_study(tmp_path)
    assert not report['mixed_clearance_envelopes']

def test_one_envelope_is_not_flagged(tmp_path):
    protocol={'order':['random','search','agent_search'],'flights_per_method':4,'qualification_directories':['t']}
    write(tmp_path,'protocol.json',protocol)
    for name in protocol['order']:
        write(tmp_path/name,'config.json',{});write(tmp_path/name,'history.json',envelope_history(.3482,.3482))
    report=report_study(tmp_path)
    assert not report['mixed_clearance_envelopes']
    assert not any('different vehicle envelopes' in s for s in report['limitations'])
