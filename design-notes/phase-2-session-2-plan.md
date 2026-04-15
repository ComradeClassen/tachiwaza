# Phase 2 Session 2 — Plan
## The Grip Graph, the Position State Machine, the Ne-Waza Door, and the Referee

*This is the brief for the next Claude Code session. It completes Phase 2 of
Ring 1. It is the largest single session in the project so far. Read it
before opening Claude Code; reference it during the session; update it at
the end with what actually shipped.*

---

## Goal

By the end of this session, a match runs with:

1. A real grip war that takes time to develop before any throw can fire.
2. Throw attempts gated on the grip graph satisfying the throw's
   prerequisites — no more throws-from-nothing.
3. Stuffed throws opening a one-tick ne-waza window with a real ground
   resolution path (escape back to standing, pin attempt with osaekomi
   clock, choke / armbar commitment chains).
4. A Referee object with four personality variables driving when Matte
   gets called and how landings get scored.
5. Hajime at start, Ippon as a final ceremonial call when match-ending
   throws land, Matte called for real reasons not random rolls.

A match log that previously read as "throw, throw, throw, IPPON" should
now read as "engagement, grip war develops, kuzushi window opens, throw
commits, lands cleanly, IPPON." Or alternatively: "engagement, stalemate,
reset, re-engage, stalemate, reset, slow grip dominance shift, eventual
window, throw stuffs, ne-waza window, pin attempt, escape, back to
standing, more grip war."

These are the two patterns real judo produces. The architecture should
produce both depending on the fighters and the rolls.

---

## File-by-file scope

### `src/enums.py` — expanded

**Add:**
- `GripType` enum: STANDARD, PISTOL, CROSS, DEEP, POCKET, HIGH_COLLAR,
  BELT, OVER_BACK, RUSSIAN, UNDERHOOK, TWO_ON_ONE, CHOKE_HOLD,
  ARMBAR_THREAT
- `GripTarget` enum (split into standing + ne-waza groups for clarity):
  - Standing: LEFT_LAPEL, RIGHT_LAPEL, LEFT_SLEEVE, RIGHT_SLEEVE,
    BACK_COLLAR, LEFT_BACK_GI, RIGHT_BACK_GI, BELT
  - Ne-waza: NECK, LEFT_WRIST, RIGHT_WRIST, LEFT_ELBOW, RIGHT_ELBOW,
    LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_KNEE, RIGHT_KNEE, LEFT_ANKLE,
    RIGHT_ANKLE, HEAD, WAIST
- `Position` enum: expand to include ne-waza positions per
  `data-model.md` v0.4
- `InjuryState` enum: HEALTHY, MINOR_PAIN, IMPAIRED, MATCH_ENDING
- `LandingProfile` enum: FORWARD_ROTATIONAL, HIGH_FORWARD_ROTATIONAL,
  REAR_ROTATIONAL, LATERAL, SACRIFICE
- `MatteReason` enum: SCORING, STALEMATE, OUT_OF_BOUNDS, PASSIVITY,
  STUFFED_THROW_TIMEOUT, INJURY, OSAEKOMI_DECISION
- `CounterAction` enum (for ne-waza commitment chains): HAND_FIGHT, FRAME,
  HIP_OUT, BRIDGE, TURNOVER, SHRIMP

**Update:**
- `BodyPart` enum: expand to 24 parts per `data-model.md` v0.4. Keep
  legacy `right_leg` / `left_leg` as enum values that resolve to the
  composite of their sub-parts (deprecated, but won't break Phase 1
  references during the migration).

### `src/judoka.py` — expanded

**Update Identity layer:**
- Add the cultural layer hooks (`nationality`, `training_lineage`,
  `style_dna`, `stance_matchup_comfort`) — declared as fields with sane
  defaults, not read by Ring 1.

**Update Capability layer:**
- Body part dict expands from 15 to 24 keys.
- Each part declares its functional flags (GRASP, STANCE, JOINT, THROAT,
  THOUGHT, NERVOUS, CONTROL_TARGET) — used by graph queries.
- `effective_body_part()` updates to read `InjuryState` enum instead of
  bool, and to apply `stun_ticks` multiplier from State.

**Update State layer:**
- Body fatigue dict expands to 24 keys.
- Body injury dict expands to 24 keys, holds `InjuryState` enum values.
- Add `stun_ticks: int` field with per-tick decay logic.
- Add the v0.3 grip sub-loop state fields if not yet present.

### `src/grip_graph.py` — NEW

The foundational data structure. Implements `grip-graph.md` v0.1.

```python
@dataclass
class GripEdge:
    grasper_id: str
    grasper_part: BodyPart
    target_id: str
    target_location: GripTarget
    grip_type: GripType
    depth: float
    strength: float
    established_tick: int
    contested: bool = False

class GripGraph:
    def __init__(self):
        self.edges: list[GripEdge] = []
    
    # Edge operations
    def add_edge(self, edge: GripEdge) -> None
    def remove_edge(self, edge: GripEdge) -> None
    def break_all_edges(self) -> list[GripEdge]  # returns broken edges for prose
    def edges_owned_by(self, fighter_id: str) -> list[GripEdge]
    def edges_targeting(self, fighter_id: str) -> list[GripEdge]
    def edges_on_target(self, fighter_id: str, location: GripTarget) -> list[GripEdge]
    
    # Engagement
    def attempt_engagement(self, fighter_a: Judoka, fighter_b: Judoka,
                           current_tick: int) -> list[GripEdge]
    
    # Per-tick maintenance
    def tick_update(self, current_tick: int, fighter_a: Judoka,
                    fighter_b: Judoka) -> list[Event]
        # ages edges, accumulates fatigue, rolls 3-tier outcomes,
        # may break edges via force-break, returns events
    
    # Throw prerequisite checks
    def satisfies(self, requirements: list[EdgeRequirement],
                  attacker_id: str) -> bool
    
    # Position transitions preserve / transform edges
    def transform_for_position(self, old_pos: Position,
                                new_pos: Position) -> list[Event]
```

The `EdgeRequirement` is a small dataclass that throws use to declare what
they need (see `grip-graph.md`).

### `src/position_machine.py` — NEW

The position state machine. Owns the rules for which Position transitions
are legal and what triggers them.

```python
class PositionMachine:
    @staticmethod
    def can_transition(from_pos: Position, to_pos: Position,
                       graph: GripGraph, fighters: tuple[Judoka, Judoka]) -> bool
    
    @staticmethod
    def determine_transition(current_pos: Position, graph: GripGraph,
                             fighters: tuple[Judoka, Judoka],
                             tick_events: list[Event]) -> Optional[Position]
        # called per tick to see if position should change
    
    @staticmethod
    def can_attempt_throw(current_pos: Position, graph: GripGraph,
                          throw: ThrowDef, attacker: Judoka) -> bool
        # gates whether the throw is even legal to attempt
    
    @staticmethod
    def can_attempt_newaza_action(current_pos: Position,
                                   action: NewazaAction) -> bool
```

### `src/throws.py` — rewritten

Throws now declare their prerequisites against the grip graph:

```python
@dataclass
class EdgeRequirement:
    grasper_part: BodyPart       # may use BodyPart.dominant_hand etc.
    target_location: GripTarget
    grip_type_in: list[GripType] = field(default_factory=list)  # empty = any
    min_depth: float = 0.0
    min_strength: float = 0.0

@dataclass
class ThrowDef:
    name: str
    requires: list[EdgeRequirement]
    posture_requirement: list[Posture]
    primary_body_parts: list[BodyPart]
    landing_profile: LandingProfile
    base_effectiveness: dict[Side, float]  # dominant / off
```

Rewrite the existing 8 throws with proper `EdgeRequirement` lists. Add 2–3
ne-waza techniques (a choke, an armbar, a pin) as `NewazaTechniqueDef`
entries that drive the multi-turn commitment chains.

### `src/referee.py` — NEW

The Referee object. Personality drives Matte timing and scoring.

```python
class Referee:
    def __init__(self, name: str, nationality: str, **personality):
        self.name = name
        self.nationality = nationality
        self.newaza_patience = personality.get('newaza_patience', 0.5)
        self.stuffed_throw_tolerance = personality.get('stuffed_throw_tolerance', 0.5)
        self.match_energy_read = personality.get('match_energy_read', 0.5)
        self.grip_initiative_strictness = personality.get('grip_initiative_strictness', 0.5)
        self.ippon_strictness = personality.get('ippon_strictness', 0.5)
        self.waza_ari_strictness = personality.get('waza_ari_strictness', 0.5)
        # internal state
        self.cumulative_passive_ticks: dict[str, int] = {}
        self.last_attack_tick: dict[str, int] = {}
    
    def should_call_matte(self, match_state: MatchState,
                          current_tick: int) -> Optional[MatteReason]
        # checked each tick; returns reason if Matte should fire
    
    def score_throw(self, landing: ThrowLanding,
                    technique_quality: float) -> ScoreResult
        # IPPON / WAZA_ARI / NO_SCORE based on personality + landing
    
    def update_passivity(self, fighter_id: str, was_active: bool,
                          current_tick: int) -> Optional[ShidoCall]
    
    def announce_hajime(self) -> Event
    def announce_matte(self, reason: MatteReason) -> Event
    def announce_ippon(self, winner_id: str) -> Event
```

For Phase 2 Session 2, hand-build two referee personalities:
- **Suzuki-sensei** (Japanese-style): high newaza_patience (0.7), low
  stuffed_throw_tolerance (0.3), high ippon_strictness (0.8) — wants clean
  judo, breathes ne-waza, resets fast on stuffed throws
- **Petrov** (European-style, sambo-influenced): moderate newaza_patience
  (0.5), high stuffed_throw_tolerance (0.7), moderate ippon_strictness
  (0.5) — gives ground action time, generous on landing angle

Use one of them per match. Phase 3 calibration will tune defaults; Ring 2+
adds more nationalities.

### `src/ne_waza.py` — NEW

The ne-waza system: position progressions, commitment chains, escapes.

```python
class NewazaResolver:
    def attempt_ground_commit(self, stuffed_throw_event: Event,
                               aggressor: Judoka, defender: Judoka,
                               window_quality: float) -> bool
        # roll for whether either fighter commits to ground
    
    def transition_to_newaza(self, from_position: Position,
                              graph: GripGraph,
                              fighters: tuple[Judoka, Judoka]) -> Position
        # determines starting ne-waza position based on how the throw stuffed
    
    def tick_resolve(self, position: Position, graph: GripGraph,
                     fighters: tuple[Judoka, Judoka],
                     osaekomi: OsaekomiClock) -> list[Event]
        # one tick of ne-waza: roll counter-actions, advance commitment chains,
        # check for escapes, update osaekomi
    
class OsaekomiClock:
    def __init__(self):
        self.holder_id: Optional[str] = None
        self.position_type: Optional[Position] = None
        self.ticks_held: int = 0
    
    def start(self, holder_id: str, position: Position) -> None
    def tick(self) -> Optional[ScoreResult]
        # 10 ticks (10 sec) = WAZA_ARI; 20 ticks = IPPON
    def break_pin(self) -> None
```

For Session 2, ship one choke chain (okuri-eri-jime), one armbar chain
(juji-gatame), and the pin clock with two pin types (kesa-gatame,
yoko-shiho-gatame). Counter-actions get 2–3 options per tick. Escapes
roll against ne_waza_skill + composure + cardio.

### `src/match.py` — rewired

The Match class becomes the conductor:

```python
class Match:
    def __init__(self, fighter_a: Judoka, fighter_b: Judoka,
                 referee: Referee, max_ticks: int = 240):
        self.fighter_a = fighter_a
        self.fighter_b = fighter_b
        self.referee = referee
        self.grip_graph = GripGraph()
        self.position = Position.STANDING_DISTANT
        self.osaekomi = OsaekomiClock()
        self.match_state = MatchState(...)
        # ...
    
    def run(self) -> MatchResult:
        self._announce_hajime()
        for tick in range(self.max_ticks):
            if self.match_state.match_over:
                break
            self._tick(tick)
        return MatchResult(...)
    
    def _tick(self, current_tick: int) -> None:
        # 1. Update body fatigue (decay, recovery, stun_ticks)
        # 2. Update grip graph (age edges, contest, force-break)
        # 3. Run sub-loop state for both fighters
        # 4. Check position transitions
        # 5. If sub-loop produces a throw: resolve_throw()
        # 6. If in NE_WAZA: ne_waza_resolver.tick_resolve()
        # 7. If osaekomi running: osaekomi.tick()
        # 8. Check referee: should_call_matte()?
        # 9. Update passivity counters
        # 10. Emit events to log
    
    def _resolve_throw(self, attacker, defender, throw_def):
        # Computes ThrowLanding (angle, impact, control)
        # Calls referee.score_throw()
        # Updates score, composure, fatigue, etc.
        # If STUFFED: opens ne_waza_window flag
```

### `src/main.py` — minimal update

- Instantiate a Referee (Suzuki-sensei by default)
- Build Tanaka and Sato with the new 24-part body model
- Run Match, print event log

---

## Build order (smallest dependencies first)

1. **`enums.py`** — extend with new enums and BodyPart expansion. Smallest
   change, enables everything else.

2. **`judoka.py`** — expand body parts, update `effective_body_part()` for
   InjuryState and stun_ticks. Add cultural layer field declarations.

3. **`grip_graph.py`** — `GripEdge`, `GripGraph`, edge ops, attempt_engagement,
   tick_update, satisfies(). This is the foundational new module.

4. **`throws.py`** — rewrite throw definitions with `EdgeRequirement`. Add
   ne-waza technique definitions.

5. **`position_machine.py`** — transition rules and gating queries.

6. **`referee.py`** — Referee class with hand-built Suzuki-sensei + Petrov.

7. **`ne_waza.py`** — NewazaResolver, OsaekomiClock, choke/armbar/pin chains.

8. **`match.py`** — rewire to use everything above. The conductor.

9. **`main.py`** — instantiate and run.

Each step is committable on its own. Don't try to land all of this in one
commit — break it into 6–8 logical commits as you go.

---

## What success looks like

Run `python src/main.py` and see a match log that:

- **Starts with Hajime** announcement (referee speaks)
- **Has visible engagement**: edges form before any throw can fire
- **Has visible grip war**: tug-of-war ticks, edges contest, some break
- **Has visible kuzushi windows**: at least one opens during a typical
  match (sometimes converted, sometimes wasted)
- **Has stifled resets**: 2–6 per match (stalemate breaks)
- **Throws fire from satisfied prerequisites**: no throw attempted from
  STANDING_DISTANT, no seoi-nage without a deep collar grip
- **STUFFED throws sometimes open ne-waza**: occasional ground transition
- **Pin attempts reach osaekomi clock**: occasional waza-ari from pin
- **Referee calls Matte for real reasons**: stalemate, out-of-bounds,
  passivity, post-stuffed-throw timeout
- **Matches end on Ippon (clean throw or submission), accumulated
  waza-ari, or time expiration**
- **Match length varies**: some end in 10–30 ticks (clean ippon early),
  some go the full 240

The single biggest validation: **run the match 20 times in a row** and
look at the variance. Different rolls should produce different sequences.
A handful of matches should end in under 30 ticks. A handful should go
the full distance. The middle should be 60–180 ticks with multiple grip
war cycles.

---

## What this session does NOT build

These get explicitly deferred to keep scope honest:

- **Coach / Matte instruction window** — Ring 2 Phase 1. The architecture
  supports it (Match.coach_view() is declared); the UI is not.
- **Coach IQ filtering implementation** — Ring 2 Phase 1. The hook is
  declared; the rendering is not.
- **Cultural layer reading** — Identity fields are declared but dormant.
  No style_dna affects engagement edge selection in this session.
- **Full prose templating** — Phase 4. Use placeholder log strings that
  mark the right moments. Sentences come later.
- **Style-specific throws** (Khabareli, Korean reverse seoi) — Ring 2 with
  the cultural layer.
- **Combo system** — declared in throws.py but not wired into sub-loop.
  Phase 3 territory.
- **Training / dojo / Ring 3 systems** — fully out of scope.
- **2D visual layer** — Ring 5.
- **Calibration tuning** — Phase 3. Ship Session 2 with rough defaults
  from `data-model.md` v0.4 and `grip-sub-loop.md` v0.2.

---

## Tactical notes for the session

**Don't try to perfect the prose log.** Use functional log lines like
`[tick 47] GRIP_FIGHT: Tanaka R.hand vs Sato L.lapel — PARTIAL, depth 0.6→0.4`.
The pretty sentences are Phase 4. The job here is to make the *events*
fire correctly so Phase 4 has good material.

**Test the position state machine in isolation first.** Before wiring it
into the full Match tick loop, write a small script that creates a
GripGraph, walks through STANDING_DISTANT → ENGAGEMENT → GRIPPING →
ENGAGED transitions manually, and prints what happens. Confirm the
transitions are sane before plugging into the real flow.

**Hand-build the ne-waza chains as small finite-state machines.** A choke
is N states with per-state counter rolls. Don't generalize yet. Get one
working, then a second, then look for the abstraction.

**Use the Phase 1 / Phase 2 Session 1 fighters as the test bed.** Tanaka
(LEVER, age 26, seoi specialist) vs. Sato (MOTOR, age 24, uchi-mata
specialist). The same fighters, now playing inside a real grip graph and
real position state machine. The contrast with Session 1's behavior
should be obvious in the log.

**Expect the first runs to look weird.** The grip graph will produce
matches that feel off until calibration. That's Phase 3's job. Session 2
ships with "the architecture is right and the rolls happen" — not "the
matches feel like elite judo."

---

## Updates to other docs after this session

After Session 2 ships, update:

- **`tachiwaza-master-doc.md`** — move "Phase 2 Session 2" from "WHAT'S
  NEXT" to "WHAT'S BEEN BUILT." Add "Phase 3 — Ring 1 Calibration" as the
  next entry.
- **`data-model.md`** — bump to v0.5 if any field signatures changed
  during implementation. Note what got added vs. what stayed declared
  but unused.
- **`grip-graph.md`** — bump to v0.2 with notes on what the spec missed
  during implementation.
- **`grip-sub-loop.md`** — bump to v0.3 with calibration notes from real
  match runs.
- **New `phase-2-session-2-recap.md`** — same format as Session 1's
  recap. What was built, what surprised you, what to think about before
  Phase 3.

Don't update before — let the session reveal what actually shipped.

---

## Open questions to resolve during the session

1. Does `attempt_engagement` create edges deterministically based on
   reach, or does it roll? (Probably rolls weighted by reach. Confirm in
   code.)

2. Should `force_attempt` (committing a throw with no kuzushi window) call
   the same `resolve_throw()` with a multiplier, or have its own resolution
   path? (Probably same path with multiplier — simpler.)

3. How does the position state machine handle the SCRAMBLE → NE_WAZA vs.
   SCRAMBLE → STANDING_DISTANT decision? (Probably a roll on each
   fighter's `ne_waza_skill` + cardio, modified by ne_waza_window_quality
   from the stuffed throw. Either fighter committing transitions both to
   NE_WAZA.)

4. Where does the osaekomi clock live — on Match or on Referee? (Match
   feels right because it's match state; Referee just reads it for
   scoring decisions.)

5. Do counter-actions in ne-waza chains roll independently per tick, or
   does the bottom fighter pick one per tick that the top must respond
   to? (Probably one per tick, picked by AI based on highest
   probability of success. Player-controlled choice is Ring 2 / play-as-
   judoka mode.)

These don't need to be answered before opening the session — they'll
resolve naturally as the code goes in.

---

*Document version: April 14, 2026 (v0.1).
Written before the Phase 2 Session 2 Claude Code session.
Update after the session with what actually shipped and what surprised you.*
