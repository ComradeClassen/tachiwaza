# Grip as Cause

*A Hajime design document. Reframes grip work from prerequisite-to-throws
into the engine that produces them. Establishes the commitment/exposure
principle as the universal lever that ties grip mechanics, skill
progression, throw availability, and signature emergence into one system.*

*Status: Design specification. No code yet. Ring 1 scope.*
*Companion to: `physics-substrate.md`, `grip-sub-loop.md`,
`biomechanics.md`, `data-model.md`.*

---

## 1. Thesis

In real judo, the grip war is not a prerequisite phase that ends when a
throw begins. The grip work *is* the throw beginning. A pull on a deep
lapel grip breaks uke's posture forward; that pull *is* the kuzushi;
the same motion that produces the kuzushi continues into the tsukuri
that places tori's hip under uke's center. Grip, kuzushi, tsukuri,
kake — these are phases of a single continuous motion, and the
grip-and-pull phase is doing the most causal work.

The current Hajime model inverts this. Grips are state. Throws are
events. The throw fires, *then* induces kuzushi as a side effect of its
own commit. Grip depth is checked at commit time as a precondition.
This produces matches where throws feel like spam — they happen *after*
the grip work but not *because* of it. The grip war becomes a
bookkeeping layer the simulation must complete before the real action
begins.

This document specifies the polarity reversal. Grip depth is potential.
Pulling on an established grip is the act that converts that potential
into kuzushi force. Grip work is the cause of throws, not their gate.
Throws fire because recent grip-driven kuzushi events have put uke in
a compromised state the throw's signature matches. The grip war is no
longer a prologue; it is the match.

The single design principle that organizes everything that follows:
**commitment creates effect and exposure proportionally, and skill
modulates the ratio between them.**

This document specifies the principle for tachiwaza. The same
principle is intended to govern ne-waza — pin force as commitment,
shrimping/framing as conversion-equivalent actions, ref patience as
the matte-and-reset trigger — but ne-waza specification is a
separate document. See §12.

---

## 2. Event-Driven Kuzushi

Kuzushi today is, roughly, a state change induced by a throw attempt.
Under the new model, kuzushi is a *force event* emitted by an explicit
pull or push action — a fighter using an established grip to actively
break uke's balance. Grip depth is the capacity that a pull can draw
on; the pull itself is the act that generates the kuzushi.

**The reframe — depth is potential, pull is conversion.** A grip's
depth level (POCKET, STANDARD, DEEP) is no longer just a static
quality the throw layer reads. Depth is a *capacity ceiling*: it
governs how much force a pull from that grip can deliver. The
deepening action does not generate kuzushi directly. It raises the
ceiling. The kuzushi event happens when the fighter explicitly
*pulls* (or pushes) on an established grip — a separate action with
its own commitment and exposure profile.

This separates two things the draft conflated. Building grip is one
activity. Using grip to break balance is another. They are
sequential, both in real judo and in this model.

**Why this matters.** A grip held at DEEP for thirty ticks with no
pulls fired generates no kuzushi. The capacity is high but no force
is being delivered. A grip at STANDARD that the fighter actively
pulls on this tick generates a moderate kuzushi event right now.
The static depth tells you about potential; the pull tells you about
live pressure. This matches real judo: a held grip without intent is
no threat, a working grip is.

**The force formula.** A pull action emits a kuzushi event whose
magnitude is computed roughly as:

```
force = f(strength, technique, experience, grip_depth)
```

where:

- **strength** is a physical attribute, substrate-derived (mass,
  build, conditioning).
- **technique** is the relevant skill axis from the skill vector
  (lapel-grip work for a lapel pull, sleeve-grip work for a sleeve
  pull, etc.).
- **experience** is per-throw or per-grip-pattern proficiency — how
  many times this fighter has executed this kind of pull before.
- **grip_depth** is the current live depth of the grip being used
  (POCKET, STANDARD, DEEP), with a multiplier for each level.

Exact weights are calibration. The principle is that all four
factors contribute and any one of them being low limits the force
ceiling — a strong fighter with no technique pulls poorly, a
technical fighter with a POCKET grip can't deliver force, an
inexperienced fighter even with depth and technique pulls
inefficiently.

**Direction.** The kuzushi event's direction is determined by the
grip type and the direction the fighter chooses to pull. A lapel
pull-down generates forward-down kuzushi. A lapel push-up generates
backward kuzushi. A sleeve pull-across generates rotational
sideways kuzushi. A collar push generates backward kuzushi.
Different pull directions from the same grip produce different
kuzushi vectors, and the fighter chooses which direction to pull
based on what they're setting up.

These vectors compose across grips. A simultaneous lapel pull-down
and sleeve pull-across feed the uchi-mata signature (forward and
rotational); a lapel pull-down alone feeds o-soto-gari more
naturally; a low sleeve pull with hip-pivot footwork feeds
seoi-nage. Throw selection becomes a question of which signature
uke's *current compromised state* — built from recent kuzushi
events — most strongly invites.

**Decay.** Kuzushi events decay. A pull two ticks ago is mostly
live; one from ten ticks ago is mostly faded. The decay curve is
a calibration question, not a design one, but it should be steep
enough that the throw layer cannot rely on stale work — if you
want a throw, you need to either ride a fresh kuzushi event or
generate one with a new pull. Holding a deep grip without pulling
produces no commit opportunity.

**Throws still fire.** This is not a removal of throws; it's a
re-grounding of when they fire. A throw commit happens when the
throw's signature finds a sufficient match in uke's recent kuzushi
history *and* the attacker decides to commit. The grip-presence
gate from HAJ-36 still applies as a structural sanity check (you
can't commit to a throw whose grip requirements you don't meet),
but the *reason* the commit happens has moved upstream into the
pull-driven kuzushi events themselves.

---

## 3. The Commitment/Exposure Principle

Every grip action is a commitment. Commitment produces effect — the
deepen advances the grip, the pull converts depth into kuzushi force,
the strip degrades opponent's grip, the defend resists pressure.
Commitment also produces exposure — the deepening fighter has loaded
their weight forward into the grip and narrowed their attention onto
their hand; the pulling fighter has loaded their weight into the
direction of force and committed their base; the stripping fighter has
committed a hand to ripping rather than defending; the defending
fighter has committed posture to resisting one direction of pressure
and is open to others.

Effect and exposure are produced together and scale together. This is
the universal lever. It applies to deepen, pull, strip, defend-grip,
reposition-grip, throw commits, and counter-window fires. Every action
in the system can be characterized by what it commits and what it
exposes.

### 3.1 Asymmetries Among Grip Actions

Deepen, pull, and strip are not symmetric to each other.

**Deepen exposes posture.** A fighter advancing their grip from
POCKET toward STANDARD or STANDARD toward DEEP must commit forward
weight, narrow their visual attention to the grip work, and load their
elbow into a specific angle. This opens *counter-attack* windows.
Specifically, an attentive opponent can read tori's loaded forward
posture and fire uchi-mata, tai-otoshi, or a hip-throw counter into
the committed weight. The deeper the deepen attempts, the larger the
window. A LEVER-grade attacker's deepen is mechanically dangerous —
which is precisely *why* it is exploitable if read correctly.

**Pull exposes base.** A fighter pulling on an established grip
commits weight in the direction of pull, loads the base, and shifts
balance toward the force vector. This opens different windows than
deepen — the puller is not reaching forward but is *anchored* in a
specific direction, which makes them vulnerable to counters that
exploit the anchor (a foot sweep into the loaded leg, a sacrifice
throw that drops under the puller's force). The harder the pull, the
deeper the anchor, the larger the window.

**Strip exposes attention with composure cost.** A fighter actively
ripping an opponent's grip has committed a hand to stripping rather
than defending. Their attention narrows to the contested grip. They
are not posture-loaded the way a deepener is or base-loaded the way
a puller is, so the counter-attack window from a strip is smaller,
but they pay a small composure cost from the frustration of contested
grip work and from the moment of defensive vulnerability while their
hand is committed elsewhere.

**Why asymmetric.** In real judo, deepening requires winning;
shallowing requires only contesting. Offense must overcome resistance
to advance the grip; defense only has to disrupt enough that depth is
lost. If the model gives deepen and strip symmetric magnitudes, the
equilibrium is cancellation — which is exactly what the seed=1
bootstrapping bug surfaced. Defensive shallowing must be structurally
easier than offensive deepening, and offensive deepening must cost
something on failure. Without this, the grip race has no decision
density: both fighters spam their respective actions and nothing
moves.

### 3.2 Deepen and Pull Are Separable

A core skill expression in this model is the ability to separate the
deepen action from the pull action that uses it.

A white belt deepens and immediately pulls in the same hyperfocused
moment — they're not yet capable of building the grip and *waiting*
for the right moment to use it. The deepen and the pull blur into
one action with maximum exposure across both phases.

A black belt deepens carefully — perhaps over several patient
actions — and *then waits*. They hold the deep grip without pulling,
sometimes for many ticks, while reading uke's posture and footwork.
When the pull comes, it comes at the moment uke's base is most
exploitable — mid-step, off-balance from a defensive shift, or
distracted by a strip attempt of their own. The black belt's pull
generates more force (the formula's experience and technique factors
are higher) *and* lands on a uke whose own state amplifies the
kuzushi.

This separability is part of what skill *is* in this model. The
ability to hold capacity without spending it is itself a high-skill
behavior. The capacity-spending action — the pull — is what most
deserves vulnerability-window scrutiny, because it is where force is
actually delivered.

### 3.3 Failed Deepens and Failed Pulls Both Cost Something

A failed deepen is not a no-op. The attacker has loaded weight forward
and narrowed attention to a transition that did not occur. They pay:
- A small composure tick (the frustration of the failed advance).
- A vulnerability window that *opened during the deepen attempt* and
  remains open for 1-2 ticks after, even though the deepen failed.
- A small footwork cost — they committed forward weight and need a tick
  to reset their base.

A failed pull (one that uke absorbs without losing balance) is also
not a no-op. The puller has anchored their base into a force vector
that uke neutralized. They pay:
- A composure tick larger than a failed deepen's, because the pull
  is a more committed action (the attacker meant to break uke and
  did not).
- A vulnerability window oriented *toward the pulled direction* —
  the puller is anchored that way and slow to recover for that many
  ticks.
- A footwork cost proportional to how cleanly the pull executed.
  A clean committed pull that uke neutralized leaves the puller
  exposed for longer than a self-canceling muddle (which had
  little force to begin with and therefore little anchor to
  recover from). Note: pull execution quality is emergent from
  skill, not chosen by the fighter — see §3.6.

This is what gives the grip war decision density. A fighter
considering a deepen is not asking "free or not free"; they are
asking "is the likely advance worth the certain exposure plus the
risk of paying twice if it fails."

### 3.4 The Vulnerability Window

When a fighter takes a committing grip action, a vulnerability window
opens on them for some duration. The window's size and orientation
depend on which action it is:

- **Deepen window:** 2-3 ticks, oriented forward (counter-attacks
  exploit the loaded forward weight).
- **Pull window:** 2-4 ticks, oriented in the direction of pull
  (counter-attacks exploit the anchored base). Generally larger
  than a deepen window because the commitment is greater.
- **Strip window:** 1-2 ticks, oriented toward the stripping hand
  (smaller because the strip is less posture-loading).

During whichever window is active:

- The committing fighter's perception is biased toward their own grip
  work and *away* from reading the opponent's overall posture and
  counter-attempts.
- The opponent's perception of the committing fighter's loaded state
  receives a bonus, scaled by the opponent's fight IQ.
- Counter-fire probability for the opponent is bumped, scaled by the
  opponent's composure (composure governs whether they can act on
  what they read).

The two attributes do different work. Fight IQ governs *reading the
exposure accurately*; composure governs *acting on what was read*.
This produces four distinct uke profiles in the vulnerability window:

| Fight IQ | Composure | Behavior |
|----------|-----------|----------|
| High | High | Reads the window, fires the right counter — the dangerous uke |
| High | Low | Reads the window but defends grip anyway — sees and freezes |
| Low | High | Misreads the window, fires confidently into nothing |
| Low | Low | Neither reads nor acts — the grip war passes them by |

The vulnerability window is symmetric across roles. Uke stripping
tori's grip exposes themselves the same way. Whoever commits more
exposes more. The patient defender who lets grips settle without
fighting them hard gives up grip depth but gains safety — a real judo
style (the Riner archetype). The frantic defender who strips
everything spends exposure on every contest. Both are valid; both
should be expressible by the model.

### 3.5 Footwork as a Parallel Attack Vector

Pull is one kuzushi-generating action family. Footwork is another.

A foot sweep (de-ashi-harai, ko-uchi-gari, ouchi-gari setup), a leg
attack used as a setup, a step into uke's space that disrupts their
base — these are kuzushi-generating actions in their own right,
emitting force through the foot rather than through a grip. They
follow the same commitment/exposure logic: a sweeping leg is a
committed action (the attacker is mid-sweep, standing on one foot,
exposed to counters that exploit the lifted leg), and a successful
sweep emits a kuzushi event with magnitude and direction (typically
sideways-down, oriented to the swept leg).

Footwork attacks are also a tactical answer to grip stalemates. A
fighter who cannot strip a strong opponent grip may instead use
footwork attacks to force uke to defend the legs, which distracts
attention from the grip and creates strip openings. This is
real-judo strategy: when you can't win the grip war directly,
change the question.

The implication for the action set: alongside `PULL`, the model
needs a `FOOT_ATTACK` action family (sweep, leg-attack-setup,
disruptive step) that operates on the same commitment/exposure
principles and feeds the same kuzushi event buffer the throw
selection layer reads. A throw like de-ashi-harai then fires
because uke's recent kuzushi history is dominated by foot-attack
events rather than pull events — different attack vector, same
downstream consumer.

This also extends the defensive triple from §9 (deny capacity,
deny conversion) to a fourth axis: **deny attack route** — the
defender uses their own footwork (mobile base, alert leg
positioning) to make foot attacks unviable, the same way they
use posture to deny pull conversion or stripping to deny grip
capacity.

### 3.6 Combo Pulls and Sequence Composition

Real judo throws rarely come from a single isolated pull. An
o-soto-gari is two pulls (lapel pull-down plus sleeve pull-back)
plus a step in plus the leg reap, executed in close sequence. An
uchi-mata is a sleeve pull-up plus a hip pivot plus the leg lift.
A seoi-nage is a lapel pull-down plus a turn-in plus the loading
of the back. The kuzushi these throws produce is not from any
single component — it is from the *temporal composition* of
multiple kuzushi-generating actions firing within a window short
enough that their effects stack.

Mechanically, this is what the recent-kuzushi-event buffer with
decay (§2) supports natively. Each pull, each foot attack, each
positional shift contributes a kuzushi event to uke's buffer. If
the events fire in close succession (before earlier events have
decayed), they sum into a compromised state strong enough to
support a throw commit. If they fire too far apart, each event
decays before the next lands and the compromised state never
reaches throw-commit threshold.

**This is the elite-vs-novice distinction.** An elite fighter
strings the components together with sequencing precision —
lapel pull at tick T, sleeve pull at tick T+1, foot attack at
tick T+2, throw commit at tick T+3 — and the kuzushi events
stack. A novice attempts the same throw but executes the
components either in the wrong order or with too much delay
between them, so the components don't compose: the lapel pull
fires, decays partially before the sleeve pull arrives, the
foot attack arrives after both have substantially faded, and
the throw commits on a barely-compromised uke and fails.

**This also resolves the soft-pull question (§13.8).**
Soft-vs-hard is not a parameter the fighter sets. It is an
emergent property of execution quality. A novice's "pull" can
mechanically cancel itself — they pull while simultaneously
stepping forward, which moves their base under the force vector
and reduces the net force delivered. They feel like they pulled
hard; they actually pulled soft. The skill axis governs
whether the fighter's body executes the pull as a clean force
event or as a self-canceling muddle. The felt difference
between soft and hard pulls is the result of sequencing
precision, not pull intention.

The action selection layer needs to be aware that combo
sequences are a thing — not by hard-coding specific
combinations, but by allowing fighters to *plan* a sequence
(intend lapel pull then sleeve pull then foot attack) and
execute it across multiple ticks with whatever sequencing
quality their skill axes support. This is where high-level
judo legibility lives: a viewer can see the elite fighter
*setting up* the throw across several ticks rather than just
firing it from grip state.

---

## 4. Skill as Commitment-Efficiency

This is the unification.

Skill, across every dimension of judo, is the collapse of deliberate
commitment into automatic motion. A white belt deepening a grip is
deliberate, novel, attention-consuming, weight-committing. A black
belt deepening the same grip is automatic — the motion has been
drilled into the body, the weight commitment is calibrated, the
attention does not narrow because the deepening is no longer the
foreground task.

Mechanically: **skill modulates the commitment/exposure ratio.** A
white belt's deepen produces a small effect and a large exposure.
A brown belt's deepen produces a larger effect and a smaller
exposure. A black belt's signature-throw deepen produces a large
effect and minimal exposure — the motion is so automatic that the
hyperfocus does not occur, the loaded weight is calibrated so as not
to over-commit, and the body is already positioned to continue into
tsukuri if the kuzushi takes.

This is why a white belt match looks like grip churn with occasional
lucky throws, and a black belt match looks like thirty ticks of
patient maneuvering toward a specific setup. They are running the
same simulation; the ratios are different; the felt experience is
different in kind.

The principle generalizes beyond grips. The same skill axis that
modulates deepen efficiency modulates throw-commit efficiency,
counter-window-read accuracy, composure recovery, ne-waza
transitions, footwork stability — every action in the simulation
can be characterized as commitment + exposure, and every action's
ratio is modulated by the relevant skill axis.

---

## 5. The Skill Vector

A fighter is not characterized by a belt; a fighter is characterized
by a vector across atomic skill axes. The belt is a readable summary
of the vector, awarded by a coach (see §7), not the underlying truth.

### 5.1 Axes (proposed Ring 1 set)

**Grip fighting**
- Lapel grip (offensive depth control)
- Sleeve grip (offensive depth control)
- Two-on-one work (committing two hands to control one)
- Stripping (degrading opponent grips)
- Defending (resisting opponent strips)
- Reposition (transitioning between grip configurations without
  releasing)
- Pull execution (sequencing precision; how cleanly the fighter
  converts grip depth into force without self-cancellation —
  see §3.6)

**Footwork (defensive / stabilizing)**
- Tsugi-ashi (following step, base-preserving)
- Ayumi-ashi (walking step, distance-closing)
- Pivots (hip rotation under load)
- Base recovery (regaining balance after committed motion)

**Footwork (offensive)**
- Foot sweeps (de-ashi-harai, okuri-ashi-harai family — timing
  and contact accuracy on uke's stepping foot)
- Leg attacks (ko-uchi-gari, ouchi-gari setups — using the leg
  as the kuzushi-generating contact)
- Disruptive stepping (intentional positional moves that force
  uke to react with their feet, opening grip changes — see §3.5)

**Fight IQ**
- Counter window reading (perception of opponent commits)
- Exposure reading (perception of opponent vulnerability windows)
- Pattern reading (recognizing setup sequences as they begin)
- Timing (reading uke's posture state to choose pull/attack
  moments — feeds the uke-posture-vulnerability term in the
  force formula; see §2)

**Composure**
- Pressure handling (composure under sustained attack)
- Ref handling (composure response to shido/scoring calls; only
  active green belt and below per existing design)
- Score handling (composure response to being scored on)

This is twenty-ish axes. Each axis is a value in some range
(probably 0-100 or 0-1, calibration question). Each axis modulates
specific actions in specific ways. The axis-to-action mapping is the
implementation surface; the axes themselves are the data structure.

### 5.2 Cross-Discipline Pre-Loads

A "white belt" in Hajime is not a fighter at zero across all axes.
It is a fighter starting their judo career. They may arrive with
backgrounds that pre-load specific axes:

- **Sambo background.** Pre-loads grip strength (lapel, sleeve),
  stripping, leg-grab analogues. Does not pre-load Japanese
  competition composure (different ref culture).
- **Wrestling background.** Pre-loads base, base recovery, pivots,
  hand-fighting (translates to two-on-one work and stripping). May
  pre-load aggressive pace (composure under pressure).
- **BJJ background.** Pre-loads ne-waza skill vectors (out of scope
  for this doc but architecturally present), composure under
  pressure, patience-reading.
- **Boxing background.** Pre-loads footwork (especially ayumi-ashi
  and pivots), head movement that translates to off-balancing reads
  in fight IQ.

A "white belt with three years of wrestling" is not a flavor tag; it
is a *specific stat vector*. A coach evaluating their progression
sees axes at non-zero starting positions and watches them climb (or
not) through training and match accumulation. This is the procedural
generation surface.

**Ring 1 scope note.** Ship the architecture for cross-discipline
backgrounds and one or two implemented examples (probably wrestling
and sambo). Don't try to calibrate four backgrounds across twenty
axes by January. The system that makes them possible plus a couple
of worked examples is the right shipping target. The rest is
post-launch content.

### 5.3 The Skyrim Accumulation Model (Ring 4 Forward-Compatibility)

In Ring 4 (Adventure Mode, see §8), the skill vector is built up
*live* by player choices: every time the player grips, they gain
points in the relevant grip axis; every time they pivot, they gain
points in pivots; every time they attempt o-goshi, they gain
proficiency on o-goshi. This is the Skyrim/Dwarf-Fortress
accumulation model — skill is what you do, repeatedly.

For Ring 1 (Fortress Mode, sim'd matches), the same vector format
is used, but the values arrive *pre-computed* at fighter generation.
The sim doesn't simulate the years of training; it consumes the
result. The architectural commitment Ring 1 makes is that the
vector format is the same in both modes — Ring 4 will read from
and write to the same data structure Ring 1 reads from. No
foreclosure.

---

## 6. Throw Availability and Signature Emergence

### 6.1 Throws Are Gated by Axes, Not by Belt

A throw is available to a fighter if the grip axes and footwork
axes that throw requires are above its specific thresholds. Belt
correlates with throw availability because belt correlates with
axis values, but the gating is on the axes themselves. An unusual
fighter — say, a green-belt judoka with brown-belt-grade lapel grip
work from a sambo background — gets access to throws their grip
work supports even though their belt rank is "lower." This is
correct. Skill is what you can do, not what color your belt is.

### 6.2 White-Belt Throw Set (Committed)

A clean-judo white belt (no cross-discipline pre-loads) has access
only to:

- **O-soto-gari** — outside reap. Single-arm grip sufficient,
  basic footwork sufficient, the canonical first throw.
- **O-goshi** — major hip throw. Single-arm grip sufficient,
  basic hip rotation footwork sufficient.
- **Ippon-seoi-nage** — single-arm shoulder throw. Single-arm grip
  sufficient (it's *one*-arm seoi-nage), basic pivot footwork
  sufficient.

These are the three throws taught in the first months of any
serious judo curriculum. They work from the grips a beginner is
taught and the footwork they have. Everything else in the throw
library requires axis values white belts haven't built yet.

### 6.3 Belt Progression of Throw Availability

- **White:** O-soto-gari, O-goshi, Ippon-seoi-nage.
- **Yellow / orange:** Add ko-uchi-gari, de-ashi-harai, basic
  uchi-mata attempts (low success rate). The menu expands as grip
  and footwork axes climb.
- **Green:** Most foundational throws available. Signature *biases*
  starting to emerge but not yet dominant.
- **Brown:** Most of the throw library accessible. Signatures
  established and biasing throw selection.
- **Black:** Full library plus strong signature dominance. Some
  throws may still be rare for specific body types but the
  accessibility is there.

The exact axis thresholds per throw are a calibration table, not a
design decision. The design decision is the gating model: axes →
throws, with belt as readable summary.

### 6.4 Signature Emergence (Option A for Ring 1)

A signature throw is the fingerprint of what a fighter has gotten
good at — not a starting condition. It emerges from the interaction
of two factors:

1. **Biomechanical substrate.** Existing system. Height, limb
   length, hip height, weight distribution, mass density predispose
   certain throws. A short, low-hipped, dense fighter has a
   seoi-nage substrate. A tall, long-limbed fighter with high hip
   mobility has an uchi-mata substrate.

2. **Accumulated proficiency.** The fighter has practiced the
   grip-and-footwork pattern that feeds the substrate-aligned
   throw, repeatedly, until it became automatic. This is reflected
   in the relevant skill axes being well above threshold for that
   throw, *and* in a per-throw proficiency value built up across
   the training history.

The signature is the throw (or two or three) where substrate and
proficiency both align highly. A short brown belt with seoi-nage
substrate and high lapel-grip + low-stance footwork gets seoi-nage
as signature. A tall brown belt with the same belt rank but
uchi-mata substrate and high sleeve-grip + pivoting footwork gets
uchi-mata. Same belt; different fingerprints.

**Below brown:** Lower belts have *biases* (substrate is doing
work; some axes are climbing faster than others) but not yet
signatures. Their grip work in a match is more exploratory — they
reach for grips because they should grip, not because the grip
builds toward a specific throw they have committed to. Throw
selection in their action selection is closer to flat across
mechanically-possible throws.

**At brown and above:** Signatures are visible in grip choices.
The fighter reaches for the grips that feed their throw. The grip
war biases toward setting up the signature, not just toward winning
position generally. This is what makes high-level matches readable
to a viewer — you can see what each fighter is *trying to do*.

**Ring 1 scope (Option A).** Signatures are pre-computed at
fighter generation. The sim does not simulate the training years
that produced them. Brown-and-up fighters arrive with signatures
already attached. Lower belts arrive with biases and the
accumulated-proficiency value at zero or low.

**Ring 4 (Option B, forward note).** When Adventure Mode lands,
signatures will *emerge* across a played career — the player's
choices in matches and training will accumulate proficiency, and
their signature will be whatever they actually got good at. The
data structure for signature should be the same in both modes; the
only difference is whether the values arrived pre-computed or were
written by play.

### 6.5 Belt as a Generation Profile

When a new fighter is generated at a specified belt rank — whether
for sim'd matches, opponent rosters, or NPCs in the dojo — the
belt rank is the input that determines the axis profile. This
makes the generation system testable: ask the simulator for a
"yellow belt" and the resulting fighter should have axis values
coherent with what yellow belt means in the model, no signatures
yet, throws available limited to the yellow-tier set, etc.

**White belt.** All grip and footwork axes near zero (with
cross-discipline pre-loads applied if specified). No signatures.
Available throws: O-soto-gari, O-goshi, Ippon-seoi-nage. Pull
execution low (frequent self-cancellation per §3.6). Fight IQ
axes near zero — they don't yet read commitments or windows
reliably. Composure varies with personality but ref-handling is
poor (relevant per existing design that ref calls affect
composure for green and below).

**Yellow / orange belt.** Grip axes climbing — typically lapel
and sleeve grip work in the low-mid range, stripping and
defending similar. Footwork axes adding the basic offensive
options (low foot sweeps available; leg attacks usable as
setups). No signatures. Throws available expanded with
ko-uchi-gari, de-ashi-harai, basic uchi-mata attempts (low
success). Fight IQ developing pattern-reading but exposure-
reading still poor. Pull execution improving but inconsistent.

**Green belt.** Most foundational throws available. Grip axes
moderate across the board; some axes climbing faster than
others depending on the fighter's biomechanical inclinations
(this is where signature *biases* start showing without
crossing into full signatures). Fight IQ reads counter windows
adequately. Composure relatively stable; ref handling
improving but still affected. Pull execution clean enough that
combo pulls of 2-3 components can succeed.

**Brown belt.** Most of the throw library accessible. Grip
axes high, footwork axes high. Signatures established (the
substrate × proficiency interaction has resolved into one or
two throws the fighter is recognizably good at). Fight IQ
high — reads exposure windows reliably and acts on them. Ref
handling no longer affects composure (per existing design).
Pull execution clean; combo sequences of 3-4 components
routine.

**Black belt.** Full throw library. All axes high, with
strong peaks in signature-supporting axes. Signatures
dominant — the fighter's grip war is visibly oriented toward
setting up their signature throw. Fight IQ very high; combo
sequences of 4+ components executed cleanly with good
sequencing precision. Composure high under nearly all
conditions.

These are generation defaults. Specific fighters at any belt
rank can deviate from the profile — a brown belt with
unusually weak stripping but exceptional pull execution; a
green belt with cross-discipline-pre-loaded footwork from a
wrestling background. The profile is the starting point for
generation, not a constraint. Variation within belt is itself
a design feature.

---

## 7. Belt Promotion as Coach Decision

A natural reading of the skill-vector model is that belt rank is
auto-assigned: when axes pass certain thresholds, the belt
auto-promotes. This is wrong. Belt promotion in real judo is a
*decision made by an instructor*, informed by the student's
demonstrated skill but not mechanically determined by it.

**The model.** When a fighter's skill vector crosses promotion
thresholds, the simulation surfaces a *suggestion* to the coach
(the player): "this fighter has reached the technical thresholds
for green belt." The player decides whether to promote. They can:

- Promote on the suggestion (responsive coaching).
- Hold the fighter at lower rank to continue stacking lower-bracket
  match wins for confidence and competitive results
  (competitive-aggressive coaching).
- Hold the fighter at lower rank because they want to see *more* —
  not just thresholds met but specific skills demonstrated, certain
  match scenarios survived, certain temperaments displayed
  (traditional coaching).
- Promote *before* thresholds are fully met if the player judges
  the fighter is ready in ways the threshold model doesn't capture
  (intuition coaching — risky but expressive).

**Per-coach promotion rules.** Different coach-players craft
different rules. What makes a green belt under one coach is not
what makes one under another. This is a real judo phenomenon —
some dojos promote fast, some slow, some on specific kata
demonstrations, some on competition results. The simulation
should let players express and discover their own coaching
philosophy through these decisions.

**Push-pull tension with the judoka.** A held-back fighter who
knows they're better than their belt rank can develop frustration.
This frustration is a composure-axis concern (the judoka's mental
state under perceived injustice). A coach who holds promotions to
guarantee competitive wins may produce technically strong but
emotionally erosive fighters — a judoka quitting because they were
never promoted is a real outcome the simulation should be able to
produce. Conversely, a coach who promotes too fast may produce
fighters whose belts overrun their actual readiness, leading to
losses at the higher bracket and confidence collapse.

This is one of the places where Hajime starts feeling like the
coaching game it is meant to be, not just a match simulator. The
belt is a *tool the coach uses* to manage the fighter's career
arc. It is not a number the system assigns.

**Ring 1 scope.** The threshold-suggestion system and the player's
ability to promote (or not) are Ring 1. The judoka's
morale/frustration response to held promotions is probably a
calibration item that lands in late Ring 1 or early Ring 2 — it
depends on whether the composure axes already model the emotional
states required. If they do, this is a small wiring task. If they
don't, defer the judoka-response side to Ring 2 and ship the
suggestion + manual-promote loop in Ring 1.

---

## 8. Ring 3 and Ring 4 Forward-Compatibility Notes

This document mentions Ring 3 (dojo persistence and world
simulation) and Ring 4 (Adventure Mode) repeatedly as forward
references. To be explicit: **no Ring 3 or Ring 4 design happens
in this document.** What this document commits to is
non-foreclosure — the data structures specified here (the skill
vector, the per-throw proficiency, the signature record, fighter
identity) should be designed such that Ring 3 and Ring 4 can read
from and write to them without restructuring.

### 8.1 Ring 4: Adventure Mode

Inspiration: Dwarf Fortress Adventure Mode. The same world, same
rules, same data; zoomed from director to participant. Fortress
Mode (Ring 1-3) sims matches and careers; Adventure Mode (Ring 4)
plays a single judoka through their career and matches firsthand.
The architectural cost of supporting Ring 4 from Ring 1 is
approximately: don't bake "this value is computed once at fighter
generation" assumptions into the data structures. Make them
assignable, mutable, and accumulating.

### 8.2 Ring 3: Dojo Persistence and World Simulation

The long-arc Hajime ambition is a Dwarf-Fortress-style
multi-dojo world. The player runs a dojo, trains its judoka
through randori sessions and local tournaments, watches their
characters develop. At any point the player can *retire the
dojo* — it continues running its daily routines under
simulation, judoka continue training and aging and competing —
and start playing a different dojo, where the same generated
characters from the original dojo can be encountered at
tournaments, with their own development trajectories continuing
in the background.

This is the central long-arc design ambition for Hajime:
populated, persistent, multi-actor world where character arcs
play out across simulation time whether the player is watching
them or not, and where switching player attention to a different
dojo doesn't pause the world.

The architectural cost from Ring 1 is the same as Ring 4's: data
structures must support unattended simulation. A fighter's skill
vector, signatures, proficiencies, age, injuries, motivation —
all of these must be readable and writable by background
simulation processes, not only by directed-play sessions. Don't
embed "this only updates when the player is watching" assumptions
in the data layer.

Ring 3 also depends on the same simulation being able to run
*coherently* without player input — meaning the action selection,
match resolution, and training-progression logic must be robust
enough that long stretches of unattended simulation produce
recognizable, story-supporting outcomes rather than degenerate
patterns. This is a higher bar than Ring 1's correctness
requirements and will surface its own design surface when Ring 3
becomes the focus.

Neither Ring 3 nor Ring 4 design happens in this document. The
notes here are about what *not* to foreclose.

---

## 9. The Defensive Mirror

Most of this document is written from tori's perspective —
attacker deepens, pulls, exposes, commits. The defensive mirror is
real and equally important.

**Uke's grip work is also commitment.** Uke stripping tori's grip
is committing a hand and an attention. Uke defending tori's grip
(holding posture, resisting the pull) is committing the same
posture they would otherwise use to attack. Uke repositioning grips
to break a setup is committing a transition. Uke pulling on their
own established grips against tori is the same kuzushi-generating
action tori uses, oriented the other way.

**Uke generates kuzushi too.** Uke's pull actions emit kuzushi
events in their own right, oriented relative to tori. A successful
sleeve pull by uke on tori is a kuzushi event for tori in the same
way the reverse would be for uke. Strips by uke on tori's grips
also have a small kuzushi consequence — tori, briefly, has lost
the tension they were maintaining and re-equilibrates backward.

**Deny capacity vs. deny conversion.** The pull/depth split (§2)
gives defense two distinct strategies that map to different defensive
styles in real judo:

- **Deny capacity** — keep tori's grips shallow. Strip aggressively,
  defend against deepens, never let the lapel get past POCKET. If
  tori has no depth, even a perfect pull generates little force. This
  is the strip-everything style — frantic, exposure-heavy, but
  effective if your stripping skill is high enough to outpace tori's
  deepens.

- **Deny conversion** — let tori build depth, but resist the pull
  itself. Maintain posture, root the base, refuse to let the loaded
  force translate into off-balance. Tori has the grip but can't use
  it. This is the patient/structural style — Riner-archetype. Less
  exposed, but requires high posture and composure axes to hold
  under sustained pull pressure.

Real fighters mix both. The mix is a function of their skill vector:
strong stripping favors deny-capacity; strong posture and composure
favor deny-conversion. The interesting matches are often
strategy-mismatch matches — a deny-capacity uke against a tori whose
depth-building is fast enough to keep getting through anyway, or a
deny-conversion uke against a tori whose pulls are strong enough to
break even rooted posture.

**The match is two-sided commitment.** At any given tick, both
fighters are in some configuration of commitment and exposure.
The match progresses through the interaction of their commitments.
A patient defender who under-commits gives up depth but accrues
no exposure penalty. An aggressive attacker who over-commits builds
depth but pays exposure on every action. The interesting matches
are the ones where the patient defender's safety eventually breaks
under sustained pressure, or the aggressive attacker's exposure
finally catches them in a counter — and which one happens depends
on the specific skill vectors at play.

This means the model does not need separate "offensive" and
"defensive" mechanics. It needs symmetric commit/expose mechanics
applied to both fighters simultaneously, with the asymmetries among
deepen, pull, and strip (§3.1) being the structural differences
between actions, not between roles.

---

## 10. Scenes This Should Produce

These are the matches the new model should make readable. If the
implementation lands and these scenes don't appear, the
calibration is off. If the implementation lands and these scenes
appear naturally, the model is doing its job.

**The white belt match.** Two white belts. Grip churn — both
fighters reach for grips they don't have a clear plan for. Brief
deepens that fail more than they succeed because the
commitment/exposure ratio is unfavorable. Failed deepens generate
small openings that the opponent's low fight IQ doesn't always
read. Eventually one fighter lucks into a grip that supports
o-goshi while the other is mid-strip and exposed; the throw fires;
ippon. Match length: short. Felt quality: chaotic but recognizable
as judo.

**The brown belt patient grip war.** Two brown belts with
different signatures (say, seoi-nage vs. uchi-mata). Thirty ticks
of grip maneuvering — the seoi-nage fighter tries to establish
a deep lapel and a low stance; the uchi-mata fighter tries to
control the sleeve and force a higher engagement. Each grip
attempt is calibrated, exposure managed, deepens spaced rather
than spammed. Crucially, both fighters *hold their built grips
without pulling* for stretches at a time, waiting for the right
posture moment in the opponent before spending the capacity.
Eventually the uchi-mata fighter catches the seoi-nage fighter
mid-step, fires a strong sleeve pull at exactly that moment;
their signature kuzushi event lands with high force (the pull
arrived on a base that wasn't grounded); they commit; the
seoi-nage fighter, who saw the commitment but couldn't get out
of position fast enough, takes the throw. Felt quality:
chess-like, readable, emergent narrative — the patience between
deepen and pull is visible.

**The mismatch.** White belt vs. brown belt. The brown belt's
grip work is so much more efficient — same actions, vastly
better commitment/exposure ratio — that the white belt's
deepens are read and exploited within two ticks every time. The
white belt scores nothing. The brown belt's signature throw lands
within the first 20 ticks. Felt quality: competence visible at
every action; the brown belt is *not* trying harder, they are
*better*.

**The Riner archetype.** A brown belt with high composure, high
defensive grip work, but moderate offensive grip work. They
under-commit on grip advances, accept lower depth, but pay almost
no exposure. The opponent struggles to find a window. Match drags
to time. The Riner-style fighter wins on shidos (opponent
penalized for passivity that was actually patience) or on a
single late opportunistic throw. Felt quality: deeply different
from the patient grip war — same patience but defensive,
opponent forced to break first.

**The Hansoku-make-by-impatience.** Two fighters, one skilled and
patient, one less skilled and aggressive. The aggressive fighter's
constant deepens accumulate exposure faster than they accumulate
depth. The patient fighter reads window after window but doesn't
fire — they're waiting for a higher-quality kuzushi event. The
aggressive fighter's composure erodes from frustration. They
commit a desperation throw on a bad signature; it fails badly;
they attempt again; another shido. Eventually hansoku-make. Felt
quality: tragic — the loser's loss is not from being out-thrown
but from being unable to wait.

These are the scenes the system should produce. Anything that
prevents them is a calibration concern.

---

## 11. Implementation Deltas

A first-pass survey of what changes. Not a ticket list — that
gets drawn from this section in a later session.

**`grip_graph.py`**
- Grip edges expose their current depth as the capacity ceiling for
  pulls; depth no longer emits kuzushi events on transition.
- Edge gains a "last interaction tick" field for recency calculations
  (so the system can tell a recently-worked grip from a stale one,
  even when the depth hasn't changed).
- Successful strips on opponent grips emit a small kuzushi event for
  the stripped fighter (the released-tension re-equilibration), but
  this is a side effect of the strip action, not a transition event.

**`actions.py`**
- New `PULL` action. Takes an owned grip (or a pair of grips) and a
  pull direction, emits a kuzushi event with computed force and
  vector. Has its own commitment cost and exposure window (§3.4).
- New `FOOT_ATTACK` action family (§3.5): foot sweep, leg attack
  setup, disruptive step. Emits kuzushi events with magnitudes and
  vectors derived from the offensive footwork axes. Has commitment
  cost and exposure window of its own (the sweeping leg is lifted,
  the attacker is briefly on one foot).
- Existing `DEEPEN`, `STRIP`, `DEFEND_GRIP`, `REPOSITION_GRIP`
  actions get explicit commitment-cost and exposure-window fields
  added (most already have de-facto costs; this makes them uniform
  and machine-readable).

**`kuzushi.py` (new)**
- The pull-force formula:
  `force = f(strength, technique, experience, grip_depth,
  uke_posture_vulnerability)`. Pure function, takes attacker
  state, grip, and uke's current posture state, returns magnitude.
  The uke_posture_vulnerability term is what makes timing matter
  (§13.6) — a pull on a grounded uke generates moderate force; the
  same pull on a mid-step uke generates substantially more.
- Foot-attack force formula, parallel structure but with offensive
  footwork axes substituting for grip technique and grip depth.
- Direction lookup: grip type + pull direction → kuzushi vector;
  foot-attack type → kuzushi vector.
- Per-fighter recent-event buffer with decay. Compromised state for
  uke is computed by summing recent kuzushi events with decay
  applied. The buffer accepts events from both pulls and foot
  attacks (and any future kuzushi-generating action family) — it
  doesn't care about source, only about the event's vector,
  magnitude, and tick.

**`action_selection.py`**
- Throw selection reads compromised state derived from kuzushi
  events, not grip depth directly.
- New decision branch: when a fighter has an established grip above
  POCKET, action selection considers whether to PULL on it now or
  hold and continue building/positioning. This decision is modulated
  by the fighter's skill axes — high-skill fighters more likely to
  hold and wait for a high-quality pull moment (when uke's posture
  vulnerability is high); low-skill fighters more likely to pull
  immediately on any established grip.
- Sequence-aware action selection: a fighter can hold a *plan*
  (intended sequence: lapel pull, then sleeve pull, then foot
  attack, then commit) across multiple ticks and execute it with
  whatever sequencing precision their skill axes support (§3.6).
  This is what makes elite combo throws different from novice
  individual-action attempts.
- Each action declares its commitment cost and exposure window.
- Action selection computes commitment/exposure trade-off modulated
  by attacker's relevant skill axis.

**`vulnerability_window.py` (new)**
- Per-fighter active window state. Opens on committing actions,
  decays over its action-specific duration (§3.4: 2-3 deepen,
  2-4 pull, 1-2 strip, foot-attack window per action subtype).
- Window has an orientation (forward for deepen, pull-direction for
  pull, hand-direction for strip, sweep-leg-direction for foot
  attack) so counters can be evaluated for whether they exploit the
  actual exposure.
- Counter-window perception and counter-fire probability read
  active windows.
- Composure-cost-on-strip applied here.

**`fighter.py` (or wherever fighter generation lives)**
- Fighter is a skill vector across the axes specified in §5.1.
- Belt is a derived/displayed value, not a primary attribute, but
  belt input drives the generation profile (§6.5).
- Cross-discipline background is a field that produces axis
  pre-loads at generation.
- Per-throw proficiency map.
- Per-grip-pattern proficiency map (feeds the experience term in
  the pull-force formula).
- Signature throws derived from substrate × proficiency at
  generation (Option A). Signatures are persistent — once
  established, the fighter gets better at *using* them but does not
  shift to a new signature (§13.5 confirmed).
- Posture state field: the fighter's current posture vulnerability,
  consumed by uke when computing pull force against this fighter.
  Updated by footwork events, recent kuzushi events received,
  current step phase.

**`promotion.py` (new)**
- Threshold-check on the skill vector emits promotion suggestions.
- Promotion is a player action, not automatic.
- Per-coach (per-player) configurable promotion rule sets
  (probably defer the rule-set authoring UI to later; ship a
  default rule set first).

**`throws.py`**
- Each throw declares its required skill-axis thresholds.
- Each throw declares its substrate alignment (what
  biomechanical profile predisposes it).
- Each throw declares which kuzushi vector profile it expects in
  uke's recent-event buffer to consider firing (composed from
  pulls and/or foot attacks).
- All three feed throw availability and signature emergence.

**`compromised_state.py`**
- Refactored to compute from kuzushi event buffer.
- The existing desperation logic remains and continues to operate
  on composure + situational triggers; the kuzushi-event-driven
  compromised state is a different axis (uke's *physical*
  compromise) than desperation (uke's *psychological* compromise).

**`narration.py` (new — abstraction layer)**
- The simulation underneath produces rich numeric state across
  ~20 axes plus event buffers, vulnerability windows, posture
  states, sequence plans. The player should not see those numbers
  directly. The narration layer translates simulation state into
  judo-readable language.
- For matches: log lines summarize what happened in coaching
  terms — "Tanaka's setup was clean" rather than "pull-execution
  axis 0.83, sequencing precision 0.77." Coaching-feedback
  summaries replace dashboards.
- For training and progression: "Tanaka's grip work has improved"
  rather than "lapel grip axis +0.03." Progression is felt
  qualitatively.
- For high-belt matches with established signatures, narration
  shifts toward Neil-Adams-style commentary (§13.9): the narrator
  *anticipates* what the fighter is trying to set up, calls the
  signature attempt as the grips are forming, anticipates uke's
  defensive options. This is what makes black belt matches feel
  legible at a high level — the simulation knows the signature,
  so it can foreshadow its arrival rather than just report it
  after the fact.
- The narration layer is the consumer of the simulation, not part
  of it. It can be evolved independently of the underlying model
  and its quality is what most directly affects player
  experience. Narration belongs in its own ticket family,
  probably staged after the core grip-as-cause refactor lands.

**`match.py`**
- Wires the new event flow.
- Tracks vulnerability windows.
- Tracks recent kuzushi event buffers per fighter.
- Surfaces all of the new state through the existing event log
  (and the HAJ-20 debug inspector). Pull events should log
  prominently — `[pull] Tanaka pulls right lapel — kuzushi
  forward 1.2` is the kind of line that makes the grip war
  legible to a viewer and lays the foundation for the narration
  layer.

**Scope warning.** This is a large delta. It is *not* a single
ticket. The grip-as-cause refactor probably wants to be staged
across at least seven tickets:

1. PULL action exists and emits kuzushi events with the force
   formula (data flow only; throws still gate on grip state for
   now).
2. FOOT_ATTACK action family added with parallel formula; events
   feed the same buffer.
3. Throw selection reads compromised-state-from-events (polarity
   reversal happens here).
4. Vulnerability window mechanics (commitment/exposure principle
   active across deepen, pull, strip, foot attack).
5. Action selection learns the deepen-vs-pull-vs-hold decision
   and sequence-aware planning (the "patience" and combo
   expressions).
6. Skill vector + axis-gated throw availability + signature
   emergence (option A) + belt-as-generation-profile.
7. Promotion suggestion system + coach-decision flow.

The narration layer is its own ticket family staged after these,
because it depends on a stable underlying simulation to translate
from.

Each ticket is independently testable, each lands a coherent
slice of the new model, and the order respects dependencies. The
existing Hajime sim should remain runnable and meaningfully
correct after each ticket, not just after all seven.

---

## 12. Out of Scope

Explicit non-commitments, so future docs and tickets don't drift
into them under this banner.

- **Ne-waza specification.** Ne-waza follows the same
  commitment/exposure principles (per §1) — pin force as
  commitment, shrimping/framing as conversion-equivalent actions,
  ref patience as the matte-and-reset trigger — but the full
  specification (axes, actions, throws-to-ground transitions,
  pin/escape mechanics, half-guard-as-pin-clock-interrupt,
  full-guard-as-reset, ref patience as a Ring 1 facet) is a
  separate document. The skill vector in §5.1 is tachiwaza only;
  ne-waza axes are an additional vector to be added when the
  ne-waza ring is specified.
- **Ring 3 dojo persistence and Ring 4 adventure mode design.**
  Forward-compatibility only, per §8.
- **Cross-discipline background calibration beyond two examples.**
  Per §5.2 scope note.
- **Coach-rule-set authoring UI.** Per §7 scope note. Default
  rule set ships in Ring 1; user-defined rule sets may come
  later.
- **Judoka frustration response to held promotions, if composure
  axes don't already support it.** Per §7. Defers to Ring 2 if
  needed.
- **Calibration of any specific numerical thresholds.** This
  document specifies design, not values. All thresholds, decay
  rates, axis ranges, and ratios are calibration items handled
  at implementation time.

---

## 13. Open Questions

Things this document does not yet resolve, listed so they don't
get forgotten. Items marked **[resolved]** were decided in the
session that produced this document and are noted here for
traceability.

1. **Decay curve for the kuzushi event buffer.** Linear?
   Exponential? Different per event magnitude? Probably
   exponential, with a short total decay window (~4-8 ticks
   total, with most of the force in the first 2-3). The right
   calibration target is a real-time-feel of ~1-2 seconds of
   live kuzushi from a single pull, with combos extending the
   compromised state through temporal stacking (§3.6). At
   Hajime's tick granularity (~quarter-second), this means the
   half-life is short — probably 2-3 ticks, not 5. Calibration
   will tell.

2. **How many axes is the right number?** The §5.1 list is
   ~25 axes (expanded from the original ~20 to include offensive
   footwork, pull execution, and timing). Confirmed approximately
   correct; the principle is "ship and let calibration tell us
   which collapse together and which need to split."

3. **Cross-discipline backgrounds beyond the obvious four.**
   What about a wrestler who also boxed? Or an MMA fighter who
   has cross-trained for years? Multi-background pre-loads
   should compose, not stack — a wrestler-boxer isn't
   double-loaded on footwork; they have a *kind* of footwork
   that's neither pure boxing nor pure wrestling. Background
   selection at character generation is rich Ring 2 territory,
   especially when combined with NPC personal goals (some
   characters want green belt and stop, some want black belt
   and won't quit).

4. **How does the player as coach perceive their fighter's
   skill vector? [resolved as design commitment]** An
   abstraction layer is the architectural answer. The
   simulation produces rich numeric state; the narration layer
   summarizes it in coaching language. Player sees "Tanaka's
   grip work has improved" rather than axis values. See
   `narration.py` in §11. Specific axis-to-language mappings
   are calibration. Important sub-decision: lower-resolution
   axes can be grouped for player feedback even when the
   underlying simulation tracks fine-grained values — improving
   right-hand lapel grip can simply add to "lapel grip"
   feedback without exposing the sub-axis.

5. **Does signature change over time? [resolved: no]** Once a
   signature is established, the fighter gets better at *using*
   it (proficiency keeps climbing within their signature
   throws), but the signature itself doesn't shift. A
   seoi-nage fighter doesn't become an uchi-mata fighter at
   30. Their seoi-nage gets sharper, their setups get more
   varied, their counters get more reliable, but it stays
   seoi-nage. Confirmed for both Ring 1 (pre-computed) and
   Ring 4 (accumulating).

6. **Does uke's posture state at the moment of pull modulate
   the kuzushi force? [resolved: yes]** This is timing — a
   pull on a grounded uke generates moderate force; the same
   pull mid-step generates substantially more. The formula
   becomes:
   `force = f(strength, technique, experience, grip_depth,
   uke_posture_vulnerability)`. The fight-IQ Timing axis
   (§5.1) governs the attacker's ability to read uke's
   posture state and pull at the high-vulnerability moment.
   This is what makes the brown-belt patient grip war
   structurally produced — patience is *for* catching uke in
   a vulnerable posture moment.

7. **Multi-grip pull combinations. [resolved: composition]**
   A fighter executing a coordinated combo (lapel pull + sleeve
   pull + step + reap, for an o-soto) emits *separate* kuzushi
   events that compose in uke's recent-event buffer (§3.6).
   The composition happens downstream. The action-selection
   layer must support sequence-aware planning so the fighter
   can intend the combo and execute it across multiple ticks
   with appropriate sequencing precision. Combo coordination
   is what separates elite from novice judo.

8. **What does a "soft pull" mean mechanically? [resolved:
   emergent]** Soft-vs-hard is not a parameter the fighter
   sets. It is an emergent property of execution quality. A
   novice's pull can mechanically cancel itself (pulling while
   stepping forward in the same tick moves the base under the
   force vector and reduces the net force delivered). The
   fighter feels like they pulled hard; they actually pulled
   soft. The pull-execution axis governs whether the fighter's
   body executes the pull as a clean force event or as a
   self-canceling muddle. Calibration question: how large is
   the force differential between a clean pull and a
   self-canceled one? Probably significant — this is what
   makes white belt judo feel different from black belt judo.

9. **Narration shifts at high belt: Neil-Adams-style
   commentary.** When a fighter has an established signature,
   the narration layer can do more than report — it can
   *anticipate*. As the fighter sets up their grips, the
   narrator calls the signature attempt before it lands ("she's
   reaching for the collar — she wants to pull right and load
   the harai"); as uke responds, the narrator anticipates uke's
   defensive options ("she's going to need to step back fast or
   the grip will be too deep to recover from"). This is what
   makes high-level matches feel legible to a viewer who isn't
   themselves a black belt — the narrator does the reading the
   viewer can't yet do. Mechanically: when narration knows the
   fighter's signature *and* sees the setup grips forming, it
   can foreshadow the throw rather than just report it after
   the fact. This belongs in the narration ticket family
   (§11), staged after the core simulation lands.

10. **Combo decay timing.** Related to question 1 but distinct:
    how *close* in time do combo components need to be for
    their kuzushi events to compose effectively? If a lapel
    pull and a sleeve pull need to land within 2 ticks of each
    other, that constrains action-selection sequencing
    significantly; if 4 ticks is fine, the constraint is
    looser. Probably the answer is "tight" — real judo combos
    are fractions of a second apart — but the calibration is
    what makes the sequencing-precision skill axis matter at
    all. If the window is too wide, low-skill fighters
    accidentally land combos; if too tight, even mid-skill
    fighters can't.

---

*End of document. Companion design notes to come on:
specific kuzushi vectors per grip type and pull direction; the
per-throw substrate-alignment table; the axis-to-throw threshold
table; the pull-force formula calibration; the foot-attack
formula calibration; the default coach promotion rule set; the
narration layer's mapping from simulation state to coaching
language.*
