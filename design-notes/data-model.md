# Judoka Data Model — Design Note v0.4

*This is the spec for the `Judoka` class. Code is implemented from this document, not the other way around. If we want to change the class, we change this doc first, then the code.*

**Changes from v0.3:**
- **Body parts expanded from 15 to 24** — added head, hips L/R, thighs L/R, knees L/R, shins L/R, wrists L/R; the legs decompose into thigh+knee+shin (foot is unchanged). Enables ne-waza graspers, joint locks, head impact, and angle-sensitive landing detection. The Capability layer carries a value per part; the State layer carries fatigue + injury per part.
- **GripEdge / GripGraph as first-class State** — the v0.3 `grip_configuration: dict` is replaced by `grip_graph: GripGraph` holding a list of `GripEdge` objects. See `grip-graph.md` for the full spec; this doc declares the fields.
- **Position state machine expanded** — the existing Position enum gains explicit ne-waza positions (TURTLE_TOP/BOTTOM, GUARD_TOP/BOTTOM, SIDE_CONTROL, MOUNT, BACK_CONTROL) and a THROW_COMMITTED transitional state.
- **Throw resolution gains landing fields** — landing_angle, impact_speed, control_maintained — read by referee personality to award IPPON/WAZA_ARI/NO_SCORE.
- **Coach IQ visibility hook** — `coach_iq_visibility(coach_iq)` declared on the Match object; returns a filtered view of the graph for Ring 2's Matte panel rendering.
- **Referee object referenced** — full spec lives in `referee.md` (forthcoming after Session 2); this doc declares how Referee personality reads from State.

---

## Design Philosophy

A `Judoka` holds three layers of information, kept structurally separate:

- **Identity** — who they are. Static or slow-changing across a career.
- **Capability** — what their body and mind can do *fresh*. Trained over months in the dojo. Persisted between matches.
- **State** — what's true *right now in this match*. Initialized fresh each match. Updated every tick.

This separation is what lets the same fighter have a great match one day and a terrible one the next: same Capability, different State trajectory.

A `Match` object holds two Judoka plus the relational state — the **GripGraph**, the position, the score, the referee. The graph is owned by the Match, not by either Judoka, because grips are by definition relational.

For Phase 2 Session 2, all three layers carry the new body parts. The grip graph becomes operational. The position state machine gates throw attempts. The Referee class drives Matte calls.

---

## Layer 1 — IDENTITY

Static or near-static. Shapes how Capability and State express themselves.

### Core identity fields

| Attribute | Type | Range / Example | Notes |
|---|---|---|---|
| `name` | str | "Tanaka" | Display name. |
| `age` | int | 16–40 | Drives the age modifier system. |
| `weight_class` | str | "-90kg" | For Ring 1, hardcoded to -90kg. |
| `belt_rank` | enum | WHITE / YELLOW / ORANGE / GREEN / BLUE / BROWN / BLACK_1 ... BLACK_5 | Determines throw vocabulary size and composure resistance to referee calls. |
| `body_archetype` | enum | LEVER / MOTOR / GRIP_FIGHTER / GROUND_SPECIALIST / EXPLOSIVE | See v0.2 definitions. |
| `dominant_side` | enum | RIGHT / LEFT | Drives dominant-side grip system. |
| `personality_facets` | dict | see v0.2 | Shapes close-call decisions and instruction reception. |

### The five physical variables (from v0.3)

| Attribute | Type | Range / Units | Role |
|---|---|---|---|
| `height_cm` | int | 155–200 | Moment arm advantage on hip throws. Reach baseline. |
| `arm_reach_cm` | int | 160–210 | Grip control radius. Who grips first at engagement. |
| `hip_height_cm` | int | 90–115 | Kuzushi geometry. Seoi entry cost changes dramatically with hip height differential. |
| `weight_distribution` | enum | FRONT_LOADED / NEUTRAL / BACK_LOADED | Frame orientation. Biases exploitable directions. |
| `mass_density` | enum | LIGHT / AVERAGE / DENSE | Two fighters at the same weight class can have very different mass distribution. |

### Cultural layer hooks (from v0.3, Ring 2+ only)

| Attribute | Type | Example | Role |
|---|---|---|---|
| `nationality` | str | "Japanese" | Biases starting style_dna. |
| `training_lineage` | list[str] | ["sensei_yamamoto_id"] | Used by voice compatibility. |
| `style_dna` | dict[StyleID, float] | {"CLASSICAL_KODOKAN": 0.6, ...} | Sums to 1.0. |
| `stance_matchup_comfort` | dict[StanceMatchup, float] | {MATCHED: 1.0, MIRRORED: 0.7} | Performance per stance matchup. |

### Personality Facets (unchanged from v0.2)

```
aggressive    ↔ patient
technical     ↔ athletic
confident     ↔ anxious
loyal_to_plan ↔ improvisational
```

---

## Layer 2 — CAPABILITY

What the body and mind can do *fresh*. Each value represents the maximum the fighter can perform when uninjured and unfatigued.

### Body Capability — 24 parts (NEW in v0.4)

The body is now organized into clusters that map to functional roles in the simulation. Each part holds a 0–10 capability value.

```
HEAD/NECK CLUSTER:
    head                                      (impact resistance, posture chain anchor)
    neck                                      (choke defense, posture defense vs. forward bend)

UPPER BODY CLUSTER:
    right_shoulder, left_shoulder             (throw entry rotational anchor, posture)
    right_bicep,    left_bicep                (pulling strength, frame breaking)
    right_wrist,    left_wrist                (joint integrity, grip security at terminal segment)
    right_forearm,  left_forearm              (grip endurance, gripping pulls)
    right_hand,     left_hand                 (grip force, terminal grasping unit)

CORE CLUSTER:
    core                                      (rotational power, posture stability)
    lower_back                                (throw lift, posture defense)

LOWER BODY CLUSTER:
    right_hip,      left_hip                  (rotational pivot for hip throws, ne-waza control)
    right_thigh,    left_thigh                (throw power, sprawl resistance)
    right_knee,     left_knee                 (joint integrity, structural under load)
    right_shin,     left_shin                 (sweeping surface, blocking, ne-waza control)
    right_foot,     left_foot                 (footwork, ashi-waza precision)
```

**Migration note:** the v0.3 model used `right_leg` and `left_leg` as composite parts. In v0.4, throws specify which sub-part they need: uchi-mata reads `dominant_thigh` and `dominant_hip`; o-soto-gari reads `dominant_thigh` and `dominant_shin`; deashi-barai reads `dominant_foot`. The old `right_leg` references in `throws.py` get rewritten in Session 2.

### Functional flags per body part (NEW in v0.4)

Inspired by DF's body part flags. Each part carries a set of functional flags that drive what it can do:

```
GRASP            — can establish grips (hands always; feet/legs in ne-waza)
STANCE           — required to stand (feet, shins, knees as load-bearing)
JOINT            — breakable through wrestling holds (wrists, elbows, knees, neck-as-cervical)
THROAT           — can be choked (neck only)
THOUGHT          — damage = match-ending (head only)
NERVOUS          — damage propagates downstream (lower_back disables hip rotation)
CONTROL_TARGET   — can be pinned for control (waist via core, shoulders, hips)
```

The flags drive what the grip graph can do with each part. Only `GRASP` parts can be graspers; only `JOINT` parts can be locked; only `THROAT` can be choked. The flags are declared once per part and queried by the graph.

### Cardio — global (unchanged)

```
cardio_capacity   (0–10)
cardio_efficiency (0–10)
```

### Mind Capability (unchanged)

```
composure_ceiling  (0–10)
fight_iq           (0–10)
ne_waza_skill      (0–10)
```

---

## Age as a Multi-Vector Modifier (unchanged from v0.2)

See v0.2 for the full age curve specification. Phase 2 Session 2 continues to use a stub `age_curve_lookup()` that returns 1.0 for everything.

---

## Dominant-Side Grip System (unchanged from v0.2)

Per-side grip strength already exists in the body model. Per-throw side modifiers and stance matchup already specified in v0.2. The grip graph reads these directly to determine edge formation probability.

---

## Layer 2 (continued) — Repertoire: Throws & Combos

```python
throw_vocabulary: list[ThrowID]
throw_profiles: dict[ThrowID, JudokaThrowProfile]
signature_throws: list[ThrowID]
signature_combos: list[ComboID]
```

**Updated in v0.4:** every throw in the registry now specifies its grip graph prerequisites (see `grip-graph.md` for the EdgeRequirement structure). A throw cannot be attempted unless the current grip graph satisfies its requirements (or it can be force-attempted with massive penalty + shido risk).

Example throw definitions in `throws.py`:

```python
SEOI_NAGE = ThrowDef(
    name="seoi-nage",
    requires=[
        EdgeRequirement(
            grasper_part=BodyPart.dominant_hand,
            target_location=GripTarget.opposite_lapel,
            grip_type_in=[GripType.DEEP, GripType.HIGH_COLLAR],
            min_depth=0.6,
        ),
        EdgeRequirement(
            grasper_part=BodyPart.pull_hand,
            target_location=GripTarget.dominant_sleeve,
            min_depth=0.3,
        ),
    ],
    posture_requirement=[Posture.UPRIGHT, Posture.SLIGHTLY_BENT],
    primary_body_parts=[
        BodyPart.lower_back, BodyPart.core,
        BodyPart.dominant_hip, BodyPart.dominant_thigh,
    ],
    landing_profile=LandingProfile.FORWARD_ROTATIONAL,
)

UCHI_MATA = ThrowDef(
    name="uchi-mata",
    requires=[
        EdgeRequirement(
            grasper_part=BodyPart.dominant_hand,
            target_location=GripTarget.opposite_lapel,
            min_depth=0.4,
        ),
        EdgeRequirement(
            grasper_part=BodyPart.pull_hand,
            target_location=GripTarget.dominant_sleeve,
            min_depth=0.4,
        ),
    ],
    posture_requirement=[Posture.UPRIGHT],
    primary_body_parts=[
        BodyPart.dominant_thigh, BodyPart.dominant_hip,
        BodyPart.lower_back, BodyPart.core,
    ],
    landing_profile=LandingProfile.HIGH_FORWARD_ROTATIONAL,
)

OKURI_ERI_JIME = ChokeDef(
    name="okuri-eri-jime",
    requires_position=[Position.BACK_CONTROL_TOP, Position.SIDE_CONTROL_TOP],
    chain_ticks=[3, 5, 4],   # establish, set, tighten
    counters_per_tick=[
        CounterAction.HAND_FIGHT,
        CounterAction.FRAME,
        CounterAction.HIP_OUT,
    ],
)
```

Belt-rank vocabulary sizes unchanged from v0.2.

---

## Layer 3 — STATE

Initialized at match start from Capability. Updated every tick.

### Body State (expanded for 24 parts)

For each of the 24 body parts:

```
fatigue:    float (0.0 – 1.0)
injured:    enum InjuryState (HEALTHY / MINOR_PAIN / IMPAIRED / MATCH_ENDING)
```

The injury field is now an enum, not a bool. This was the right call — match-ending injuries are a separate state from "the shoulder is bothering him." Effective strength formula now reads:

```python
def effective_body_part(self, part: BodyPart) -> float:
    base = self.capability[part]
    age_mod = age_curve_lookup(part, self.identity.age)
    fatigue_factor = 1.0 - self.state.fatigue[part]
    injury_factor = {
        InjuryState.HEALTHY: 1.0,
        InjuryState.MINOR_PAIN: 0.85,
        InjuryState.IMPAIRED: 0.40,
        InjuryState.MATCH_ENDING: 0.0,  # match should already be over
    }[self.state.injured[part]]
    return base * age_mod * fatigue_factor * injury_factor
```

### Cardio State (unchanged)

```
cardio_current   (float, 0.0 – 1.0)
```

### Mind State (unchanged)

```
composure_current              float (0.0 – composure_ceiling)
last_event_emotional_weight    float
stun_ticks                     int      # NEW: ticks remaining of stun from hard impact
```

`stun_ticks` is the new field for the impact-recovery system noted in the research. While `stun_ticks > 0`, all body part effective values are multiplied by a stun_factor (0.5 for hard slam, 0.7 for moderate). Decays by 1 per tick.

### Match State (significantly expanded in v0.4)

The Match object holds shared state. Per-fighter match state is below.

#### Match-level state

```python
class MatchState:
    grip_graph              GripGraph        # NEW: see grip-graph.md
    position                Position         # expanded enum (see below)
    fighter_a_posture       Posture          # UPRIGHT / SLIGHTLY_BENT / BROKEN
    fighter_b_posture       Posture
    fighter_a_stance        Stance           # ORTHODOX / SOUTHPAW
    fighter_b_stance        Stance
    stance_matchup          StanceMatchup    # MATCHED / MIRRORED (derived)
    score                   ScoreState       # waza-ari per fighter, ippon flag
    shidos                  dict[FighterID, int]
    osaekomi_clock          OsaekomiClock    # NEW: tracks pin time + holder
    ne_waza_window_open     bool             # one-tick flag after STUFFED
    ne_waza_window_quality  float            # 0.0–1.0; how good the opening was
    referee                 Referee          # NEW: full referee object
    matte_just_called       bool             # for one-tick prose hooks
    match_over              bool
    winner                  Optional[FighterID]
    ticks_run               int
    recent_events           list[Event]      # rolling window for prose density
```

#### Per-fighter match state

```python
class FighterMatchState:
    body_state              BodyState        # 24 fatigues + 24 injuries + stun_ticks
    cardio_current          float
    composure_current       float
    last_event_weight       float
    current_instruction     Optional[Instruction]
    instruction_received_strength  float
    
    # Grip sub-loop state (from v0.3)
    grip_subloop_state            SubLoopState
    grip_delta                    float
    time_in_current_state         int
    stifled_reset_count           int
    time_since_last_engagement    int
    sub_loop_config               SubLoopConfig
```

### Position enum (expanded in v0.4)

```python
class Position(Enum):
    # Standing positions
    STANDING_DISTANT       = auto()  # no contact
    ENGAGEMENT             = auto()  # closing, first edges forming
    GRIPPING               = auto()  # mutual edges, sub-loop running
    ENGAGED                = auto()  # kuzushi window achieved
    THROW_COMMITTED        = auto()  # mid-throw, can't bail
    SCRAMBLE               = auto()  # post-stuffed-throw window
    
    # Ne-waza positions (NEW in v0.4)
    NEWAZA_NEUTRAL         = auto()  # both on ground, no clear top
    TURTLE_TOP             = auto()
    TURTLE_BOTTOM          = auto()
    GUARD_TOP              = auto()
    GUARD_BOTTOM           = auto()
    SIDE_CONTROL_TOP       = auto()
    SIDE_CONTROL_BOTTOM    = auto()
    MOUNT_TOP              = auto()
    MOUNT_BOTTOM           = auto()
    BACK_CONTROL_TOP       = auto()
    BACK_CONTROL_BOTTOM    = auto()
```

The position state machine governs which actions are available. Throw attempts require GRIPPING or ENGAGED. Choke attempts require BACK_CONTROL_TOP or SIDE_CONTROL_TOP. Pin osaekomi requires SIDE_CONTROL_TOP, MOUNT_TOP, BACK_CONTROL_TOP, or kesa-gatame variants.

### Throw landing — the new resolution fields (NEW in v0.4)

When a throw resolves, in addition to the technique-execution score, a landing profile is computed:

```python
@dataclass
class ThrowLanding:
    landing_angle:        float  # 0° = flush dorsal, 90° = on side, 180° = face down
    impact_speed:         float  # 0.0–1.0 normalized
    control_maintained:   bool   # did tori keep the grip / direction through landing?
    landing_body_part:    BodyPart  # which part of uke contacts mat first
    rotation_completed:   bool   # full forward rotation, or did uke land mid-rotation?
```

The Referee then reads this landing object and the technique-execution score to award the score. **The ref's personality drives borderline calls.** A strict ref calls IPPON only on flush dorsal landings with impact + control. A generous ref calls IPPON on a 25-degree angled landing if the rest of the throw was textbook. This is where the four referee personality variables become observable.

### Referee personality (NEW in v0.4 — full spec in forthcoming `referee.md`)

```python
class Referee:
    name:                      str
    nationality:               str  # Ring 2+: biases coaching language preferences
    
    # The four personality variables
    newaza_patience:           float  # 0.0–1.0; how long ne-waza breathes before Matte
    stuffed_throw_tolerance:   float  # 0.0–1.0; how fast Matte fires after stuffed throw with no ground commit
    match_energy_read:         float  # 0.0–1.0; do they factor whether both fighters look spent?
    grip_initiative_strictness:float  # 0.0–1.0; how fast passive grip behavior earns shido
    
    # Scoring tendencies
    ippon_strictness:          float  # 0.0 generous ↔ 1.0 strict on landing angle
    waza_ari_strictness:       float
    
    # Internal state
    cumulative_passive_ticks:  dict[FighterID, int]   # for shido escalation
    last_attack_tick:          dict[FighterID, int]
```

Referee personality affects:
- **When Matte fires** — high `stuffed_throw_tolerance` lets ne-waza windows breathe; low value resets fast
- **What scores get awarded** — `ippon_strictness` is the dial on landing angle calls
- **When shidos accumulate** — `grip_initiative_strictness` and `cumulative_passive_ticks` drive passivity calls
- **Composure cost on calls** — low-belt fighters take a hit when matte is called early on a near-throw; high-belt fighters don't

The Referee is shared across the match — both fighters get judged by the same personality.

### Coach IQ visibility (NEW in v0.4 — Ring 2 hook)

The Match exposes a method that returns a filtered view of the graph for the Matte panel:

```python
def coach_view(self, coach_iq: float) -> CoachView:
    """Returns a filtered view of the match state for the coach's chair.
    
    Higher coach_iq reveals more of the underlying graph and physics.
    Ring 1 doesn't call this; Ring 2 Matte panel does.
    """
```

Three tiers (5–7 / 1–4 / 8–10) — see `grip-graph.md` for the detail.

### Tournament Carryover (Ring 2 prep, unchanged)

```
matches_today                     int
cumulative_fatigue_debt           dict[body_part, float]
emotional_state_from_last_match   enum
```

Now operates on 24 body parts.

---

## What Phase 2 Session 2 Builds From This Spec

✅ Body part expansion: 15 → 24 parts in `judoka.py` Capability, fatigue dict, injury dict

✅ `InjuryState` enum replaces injury bool

✅ `stun_ticks` field on FighterMatchState with per-tick decay logic

✅ `BodyPart` enum expanded; functional flags declared per part

✅ `Position` enum expanded with all ne-waza states

✅ `GripEdge`, `GripGraph`, `GripType`, `GripTarget` declared in new `grip_graph.py` per `grip-graph.md`

✅ Grip graph as Match-level state replacing `grip_configuration` dict

✅ Position state machine in new `position_machine.py`; gates throw attempts on GRIPPING/ENGAGED

✅ Throw definitions in `throws.py` rewritten with `EdgeRequirement` lists

✅ `ThrowLanding` computation in `resolve_throw()` with landing_angle, impact_speed, control

✅ `Referee` class in new `referee.py` with four personality variables; reads landing for scoring

✅ Matte detection driven by referee, not random

✅ `OsaekomiClock` for pin scoring

✅ Ne-waza window opening on STUFFED with quality variable

✅ Multi-turn ne-waza commitment chains for choke / armbar / pin (using counter-actions per tick)

✅ Composure changes wired to scoring events (defender takes hit on score against)

✅ Belt rank gates composure hits from referee calls (GREEN and below feel it; BROWN+ don't)

✅ Hajime ceremonial call at match start; Ippon as final call

✅ Shido tracking for forced attempts under stress; cumulative passive tick counter

## What Phase 2 Session 2 Does NOT Build

- Coach instructions UI / Matte window panel rendering — Ring 2 Phase 1
- Coach IQ filtering implementation — Ring 2 Phase 1 (the hook is declared)
- Cultural layer reading — declared in Identity but dormant
- Full prose templating — Phase 4
- Style-specific throws (Khabareli, Korean reverse seoi, etc.) — Ring 2 / cultural layer
- Training / dojo / Ring 3 systems

---

## Open Calibration Questions (for Phase 3)

These will be tuned by watching many matches in Phase 3:

- Edge fatigue rate per grip type
- Force-break threshold and probability per tick
- Engagement edge formation probability as a function of reach asymmetry
- Kuzushi window thresholds by throw type
- Referee `stuffed_throw_tolerance` defaults
- Landing angle thresholds for IPPON / WAZA_ARI / NO_SCORE
- Osaekomi timer (10s waza-ari, 20s ippon are IJF rules; calibrate escape rates)
- Ne-waza window quality multipliers
- Composure hit per scoring event
- Forced-attempt success multiplier (default 0.15 from v0.3 sub-loop config)
- Shido escalation rate from forced attempts

---

## Open Architectural Questions

- Should `grip_graph` move from MatchState to its own object that both fighters can reference? (Probably yes — easier to query from either side.)
- How are EdgeRequirements specified for left-handed fighters? The throws.py uses `dominant_hand` / `pull_hand` which resolves at runtime per fighter. Verify this resolves cleanly for both stances.
- Does the Referee know about cultural style at all in Ring 1 / Phase 2? Probably no — referee personality is independent of fighter culture in Ring 1; ref-culture interaction is Ring 2+.

---

*Document version: April 14, 2026 (v0.4). Update before changing the class.*
