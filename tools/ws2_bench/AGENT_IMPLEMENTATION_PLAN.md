# WS2 Agent and Search Implementation Plan

The plan is to build a small, controlled agent layer around the existing WS2
bench, without replacing the parts that already work. The implementation will
use plain Python, without Mastra or LangChain.

## Target workflow

```text
past results
    |
    v
agent chooses a test idea
    |
    v
search chooses valid settings
    |
    v
bench validates the configuration
    |
    v
clean flight -> attacked flight
    |
    v
results are saved and used in the next round
```

The agent never controls ROS, Isaac Sim, Docker, or the drone directly.

## Scope

For the first version, the agent may change:

- saved obstacle layout and seed
- added sensor delay
- patch on/off
- patch size
- patch start time and duration

It may not change:

- RGB or depth noise
- patch texture, color, opacity, or height
- planner code or mission limits
- start or goal during a clean/attack pair
- arbitrary files, commands, or simulator code

Add a new `delay_patch` profile. Do not reuse the existing `combined` profile,
because that also enables noise.

Initial agent limits will use the bench's existing engineering ranges:

- delay: `0-0.25 s`
- patch size: `0.3-0.9 m`
- patch timing: bounded by the mission duration
- layouts: the existing 24 easy, medium, and hard layouts

## Phase 1: Define the test contract

Add a strict proposal schema containing:

```json
{
  "hypothesis": "late patch exposure after entering a narrow layout",
  "layout": "medium",
  "layout_seed": 3,
  "delay_s": 0.15,
  "patch_enabled": true,
  "patch_size_m": 0.6,
  "patch_start_s": 5,
  "patch_duration_s": 10
}
```

The validator will:

- reject unknown fields
- reject nonzero noise
- enforce all ranges
- require one planner per campaign
- ensure the flight budget is even
- create the clean twin automatically
- keep geometry, lighting, initial state, mission, and planner identical
- disable only delay and patch in the clean flight

Likely changes:

- add `agent_schema.py`
- extend `conditions.py`
- extend the profile choices in `campaign.py`, `feedback.py`, and `dashboard.py`

Existing profiles will remain unchanged so old campaigns can still be replayed.

## Phase 2: Create one reusable adaptive campaign loop

The current adaptive logic is embedded in `feedback.py`. Separate policy
selection from flight execution.

Each policy will implement something like:

```python
proposal = policy.choose_next(history, limits, remaining_budget)
```

The shared campaign runner will then:

1. Validate the proposal.
2. Save it before execution.
3. Run the clean flight.
4. Run the attacked flight.
5. Classify the pair.
6. Save the result and evidence.
7. Give the structured result back to the policy.
8. Repeat until the flight budget is used.

Saving the decision before execution preserves the current resume behavior.
Resuming a campaign must not call the LLM again or change a saved proposal.

## Phase 3: Implement the three comparison methods

All three methods will use the same proposal schema, parameter limits, planner,
and flight budget.

### Random

Use seeded random sampling across:

- saved layouts
- delay
- patch size
- patch timing

It must produce the same proposals again when given the same seed.

### Search only

A deterministic search policy will:

- begin with broad coverage of layouts and settings
- use minimum clearance, progress, completion time, and outcome as feedback
- keep promising layouts
- adjust one parameter at a time
- repeat an apparent clean-pass/attack-fail case once
- avoid already tested configurations

Infrastructure errors will not influence the search.

### Agent plus search

The LLM will receive only a structured summary:

- tested configurations
- clean and attacked outcomes
- clearance and progress
- confirmed or unconfirmed failures
- remaining budget
- allowed actions and ranges

The LLM will return a high-level hypothesis and a bounded region to explore.
The same deterministic search code will select the exact valid proposal inside
that region.

This allows us to measure whether the LLM's ideas add value beyond search alone.

## Phase 4: Connect the LLM

Use a small plain-Python provider interface with structured JSON output.

The provider layer will include:

- model name and endpoint configuration
- timeout and bounded retry
- JSON-schema validation
- one repair attempt for invalid output
- prompt, response, model, and schema version logging
- API key read only from an environment variable or OSMO secret

A fake provider will be used in tests. CPU tests must not need network access or
an API key.

If the model fails or returns invalid data, no flight will start.

## Phase 5: Run the saved-layout pilot

Start with MonoNav.

Run:

- random: 8 flights = 4 clean/attack pairs
- search only: 8 flights = 4 pairs
- agent plus search: 8 flights = 4 pairs

That is 24 scheduled flights total. Infrastructure retries are reported
separately and do not silently increase the research budget.

This pilot only checks that the full loop works. Four pairs per method are not
enough to support a research claim.

Compare:

- valid proposals
- clean-baseline success
- clean-pass/attack-fail cases
- repeated failures
- minimum clearance
- time to first candidate failure
- actual attempts and GPU time
- duplicate or rejected proposals

## Phase 6: Add new obstacle positions

After the saved-layout loop works, implement the roadmap for generated
placements.

The agent will describe a spatial idea such as:

- obstacle near a turn
- narrower passage
- alternating obstacles
- obstacle near the final approach

A seeded generator, not the LLM, will produce coordinates.

The generated placement record will contain:

- generation seed
- object type and source asset
- explicit realized transforms
- object bounds
- Office asset hash
- protected-region checks
- overlap and floor-support checks
- route-feasibility result

The runtime will accept either:

- a saved catalog layout
- explicit realized placements

The clean and attacked flights will use the exact same realized coordinates.
Replay will use the saved coordinates directly and will never ask the LLM to
regenerate them.

This will mainly extend:

- `office_variants.py`
- `prepare_difficulty.py`
- `conditions.py`
- `launch_office.py`
- `layout_summary.py`

## Phase 7: Reporting and dashboard

Add policy selection to the dashboard:

- random
- search only
- agent plus search

Show:

- target planner
- scheduled and completed flights
- current hypothesis
- selected settings
- clean/attack result
- remaining budget
- rejected proposals
- infrastructure attempts

Reports will keep two separate finding groups:

- attack-induced: clean passes and attacked flight fails
- environment-only: clean flight already fails

Environment-only failures are still useful, but they cannot be reported as
attack successes.

## Test plan

CPU tests will cover:

- noise is always zero in the new profile
- invalid agent fields and values are rejected
- random proposals are deterministic
- search does not repeat a configuration
- clean twins preserve the complete scene
- patch timing works and remains disabled in clean flights
- saved decisions resume without another model call
- infrastructure errors do not guide search
- candidate failures are repeated exactly
- different planners have separate histories
- generated obstacles do not overlap
- protected start and goal regions stay clear
- a coarse route still exists
- replay restores identical transforms and fingerprints

Then run:

1. all existing WS2 CPU tests
2. new policy and placement tests
3. `--resolve-only` campaigns for all three methods
4. one two-flight OSMO smoke test
5. the 24-flight MonoNav pilot
6. evidence review
7. the same process for Kim

## Acceptance criteria

The MVP is complete when:

- all old tests still pass
- the agent path cannot enable noise
- all three methods use the same action space and scheduled flight budget
- campaigns can stop and resume without changing decisions
- every proposal and model response is recorded
- clean/attack pairs have identical scenes
- at least one saved campaign can be replayed exactly
- OSMO completes the MonoNav pilot and produces comparable reports

The first implementation step is the no-noise proposal schema and reusable
policy interface.
