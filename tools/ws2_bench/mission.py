"""Model-specific evaluation; Kim remains a reactive policy without a goal."""
import math

SUCCESSES={'goal_reached','completed_horizon'}
EXCLUDED={'infrastructure_error','user_stopped'}

def agent_mission(planner,mission):
    """Only expose parameters actually consumed by the selected planner."""
    common={'mission_mode','timeout'}
    fields=({'goal_distance','goal_radius','velocity'} if planner=='mononav' else
            {'minimum_travel','minimum_displacement','maximum_stationary_fraction',
             'initial_speed','maximum_speed','trajectory_horizon'})
    return {k:v for k,v in (mission or {}).items() if k in common|fields}

def defaults(planner):
    if planner=='kim':
        return dict(mission_mode='avoidance',timeout=120.,goal_distance=8.,goal_radius=.5,
                    minimum_travel=3.,minimum_displacement=1.,maximum_stationary_fraction=.5,initial_speed=.2,maximum_speed=.35,
                    trajectory_horizon=2.,velocity=.4)
    # Both depth-confidence gates are MonoNav-only. Setting either to 0 flies
    # the pre-fix behaviour for that gate.
    #
    # max_unmapped_gap is off, because the 2026-10-08 A/B showed it grounds the
    # planner rather than protecting it. It asks that every trajectory point lie
    # within the gap of a weighted voxel, but Open3D allocates blocks only in
    # the +/-trunc band around an observed surface (8 * 3/64 m = 0.375 m), so
    # 'near a mapped voxel' means 'near a wall'. Together with min_dist2obs=0.5
    # that admits only a 0.5 m < d < 0.725 m shell, and the open centre of a
    # 0.9 m corridor is rejected as unmapped for being open. Both gated flights
    # stopped at under 0.3 m travelled with depth_ok=True, while the ungated
    # twin reached the goal. Re-enable only once the test is a frustum/depth
    # check for 'have we observed this point', which is the intended meaning.
    return dict(mission_mode='goal',timeout=180.,goal_distance=8.,goal_radius=.5,
                minimum_travel=3.,minimum_displacement=1.,maximum_stationary_fraction=.5,initial_speed=.4,maximum_speed=.5,
                trajectory_horizon=2.,velocity=.3,max_unmapped_gap=0.,zoe_degenerate_min_correspondence=.12)

def motion_metrics(samples):
    if not samples:return {'max_displacement_m':0.,'mean_speed_m_s':0.,'stationary_fraction':None}
    length=sum(math.dist(a['position_m'],b['position_m']) for a,b in zip(samples,samples[1:]))
    duration=samples[-1]['sim_time_s']-samples[0]['sim_time_s']
    # One-second windows prevent sub-frame position noise from dominating stop time.
    windows=[];anchor=samples[0]
    for s in samples[1:]:
        dt=s['sim_time_s']-anchor['sim_time_s']
        if dt>=1:
            windows.append((dt,math.dist(s['position_m'],anchor['position_m'])/dt));anchor=s
    return {'max_displacement_m':max(math.dist(samples[0]['position_m'],s['position_m']) for s in samples),
            'mean_speed_m_s':length/duration if duration>0 else 0.,
            'stationary_fraction':sum(dt for dt,v in windows if v<.03)/sum(dt for dt,v in windows) if windows else None}

def horizon_outcome(config,samples):
    if config['mission_mode']=='goal':return 'timeout'
    length=sum(math.dist(a['position_m'],b['position_m']) for a,b in zip(samples,samples[1:]))
    motion=motion_metrics(samples)
    return ('completed_horizon' if length>=config['minimum_travel'] and
            motion['max_displacement_m']>=config['minimum_displacement'] and
            motion['stationary_fraction'] is not None and motion['stationary_fraction']<=config['maximum_stationary_fraction']
            else 'insufficient_progress')
