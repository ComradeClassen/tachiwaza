# debug_inspector.py
# HAJ-20 — calibration-observation overlay.
#
# Off by default. With `--debug`, the match stream carries compact handles
# ([F#A], [G#03], [T#01]) next to events, and the tick loop pauses at
# configurable trigger events to drop into a lightweight REPL. The REPL
# resolves any handle into a full state dump — the "point at it and read
# it back to me" mechanism for calibration sessions.

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import Event, GripEdge
    from match import Match, _ThrowInProgress


# ---------------------------------------------------------------------------
# PAUSE TRIGGERS
# Each category maps to a set of Event.event_type values. The REPL opens on
# the first matching event in a tick's event list. Defaults chosen so that a
# --debug run pauses on the narratively meaningful beats and nothing else.
# ---------------------------------------------------------------------------
PAUSE_TRIGGERS: dict[str, tuple[str, ...]] = {
    "throw":       ("THROW_ENTRY", "COUNTER_COMMIT", "THROW_ABORTED", "THROW_STUFFED"),
    "score":       ("IPPON_AWARDED", "THROW_LANDING", "SCORE_AWARDED"),
    "kuzushi":     ("KUZUSHI_INDUCED",),
    "matte":       ("MATTE",),
    "ne_waza":     ("NEWAZA_TRANSITION", "SUBMISSION_VICTORY", "ESCAPE_SUCCESS"),
    "shido":       ("SHIDO_AWARDED",),
    "desperation": ("OFFENSIVE_DESPERATION_ENTER", "OFFENSIVE_DESPERATION_EXIT",
                    "DEFENSIVE_DESPERATION_ENTER", "DEFENSIVE_DESPERATION_EXIT"),
}

DEFAULT_PAUSE_ON: frozenset[str] = frozenset({
    "throw", "score", "kuzushi", "matte", "ne_waza", "desperation",
})


# ---------------------------------------------------------------------------
# HANDLE ENTRY
# One row in the registry. `describe` is a closure so we always render the
# object's *current* state, not a snapshot. `alive` lets the REPL flag
# expired entries (e.g. a grip edge that was stripped two ticks ago).
# ---------------------------------------------------------------------------
@dataclass
class HandleEntry:
    handle:   str
    kind:     str                          # "fighter" | "grip" | "throw" | "ref"
    label:    str                          # short one-liner for `list`
    describe: Callable[[], str]            # multi-line detail renderer
    alive:    Callable[[], bool] = field(default=lambda: True)


# ===========================================================================
# DEBUG SESSION
# ===========================================================================
class DebugSession:
    """Owns the handle registry, event annotation, and pause/REPL flow."""

    def __init__(self, pause_on: Optional[set[str]] = None) -> None:
        self.pause_on: set[str] = (
            set(pause_on) if pause_on is not None else set(DEFAULT_PAUSE_ON)
        )
        self._handles: dict[str, HandleEntry] = {}
        self._by_pyid: dict[int, str] = {}          # id(obj) → handle
        self._next_grip_n: int = 1
        self._next_throw_n: int = 1

        # Last-seen throw handle per attacker name — sub-events and landings
        # don't re-carry the throw identity, so we stamp the most recent one.
        self._attacker_current_throw: dict[str, str] = {}

        self._match: Optional["Match"] = None
        self._quit_requested: bool = False

    # -----------------------------------------------------------------------
    # BINDING
    # -----------------------------------------------------------------------
    def bind_match(self, match: "Match") -> None:
        """Called by Match.__init__ after the match is fully constructed."""
        self._match = match
        self._register_fighter(match.fighter_a, "F#A")
        self._register_fighter(match.fighter_b, "F#B")
        self._handles["R#1"] = HandleEntry(
            handle="R#1", kind="ref",
            label=f"{match.referee.name} (referee)",
            describe=lambda: _describe_referee(match.referee),
        )
        self._handles["M#1"] = HandleEntry(
            handle="M#1", kind="match",
            label="match state",
            describe=lambda: _describe_match(match),
        )

    def print_banner(self) -> None:
        triggers = ", ".join(sorted(self.pause_on)) if self.pause_on else "(none)"
        print("[debug] DEBUG MODE ENABLED — "
              f"pauses on: {triggers}.")
        print("[debug] Handle key: "
              "F# fighter, G# grip edge, T# throw attempt, R# referee, M# match.")
        print("[debug] At a pause: type a handle to expand it, "
              "`list` for all handles, `help` for more. Enter resumes.")
        print()

    # -----------------------------------------------------------------------
    # REGISTRATION
    # -----------------------------------------------------------------------
    def _register_fighter(self, fighter: "Judoka", handle: str) -> None:
        match = self._match
        self._handles[handle] = HandleEntry(
            handle=handle, kind="fighter",
            label=fighter.identity.name,
            describe=lambda f=fighter: _describe_fighter(f, match),
        )
        self._by_pyid[id(fighter)] = handle

    def _ensure_grip_handle(self, edge: "GripEdge") -> str:
        existing = self._by_pyid.get(id(edge))
        if existing is not None:
            return existing
        handle = f"G#{self._next_grip_n:02d}"
        self._next_grip_n += 1
        self._by_pyid[id(edge)] = handle
        match = self._match

        def _alive(e=edge) -> bool:
            if match is None:
                return False
            return e in match.grip_graph.edges

        self._handles[handle] = HandleEntry(
            handle=handle, kind="grip",
            label=(
                f"{edge.grasper_id} {edge.grasper_part.value} → "
                f"{edge.target_id} {edge.target_location.value}"
            ),
            describe=lambda e=edge: _describe_grip(e, match),
            alive=_alive,
        )
        return handle

    def _ensure_throw_handle(
        self, tip: "_ThrowInProgress", attacker_name: str,
    ) -> str:
        existing = self._by_pyid.get(id(tip))
        if existing is not None:
            self._attacker_current_throw[attacker_name] = existing
            return existing
        handle = f"T#{self._next_throw_n:02d}"
        self._next_throw_n += 1
        self._by_pyid[id(tip)] = handle
        self._attacker_current_throw[attacker_name] = handle
        match = self._match

        def _alive(t=tip) -> bool:
            if match is None:
                return False
            return match._throws_in_progress.get(t.attacker_name) is t

        self._handles[handle] = HandleEntry(
            handle=handle, kind="throw",
            label=f"{tip.attacker_name} → {_throw_name(tip.throw_id)}",
            describe=lambda t=tip: _describe_throw(t, match),
            alive=_alive,
        )
        return handle

    # -----------------------------------------------------------------------
    # EVENT ANNOTATION
    # Appended to each printed event line when debug is on. Kept to one or
    # two tags — any more is clutter. Registry is updated as a side effect.
    # -----------------------------------------------------------------------
    def annotate_event(self, ev: "Event") -> str:
        if self._match is None:
            return ""
        tags: list[str] = []

        # Throw handle — register/refresh on THROW_ENTRY; stamp on sub-events
        # and landings using the last-seen throw for the attacker.
        if ev.event_type == "THROW_ENTRY":
            attacker_name = _infer_attacker_from_entry(ev, self._match)
            if attacker_name is not None:
                tip = self._match._throws_in_progress.get(attacker_name)
                if tip is not None:
                    tags.append(self._ensure_throw_handle(tip, attacker_name))
                else:
                    # N=1 throws resolve within the same tick without storing a
                    # _ThrowInProgress — allocate a one-shot throw handle so
                    # the line still carries a T# tag.
                    tags.append(self._allocate_oneshot_throw_tag(ev, attacker_name))
        elif ev.event_type.startswith("SUB_") or ev.event_type in (
            "THROW_LANDING", "THROW_ABORTED", "THROW_STUFFED",
        ):
            attacker_name = _guess_attacker_from_description(ev, self._match)
            if attacker_name is not None:
                h = self._attacker_current_throw.get(attacker_name)
                if h is not None:
                    tags.append(h)

        # Grip handle — grip events carry id() of the edge in data.
        edge_pyid = ev.data.get("edge_id") if ev.data else None
        if edge_pyid is not None:
            for edge in self._match.grip_graph.edges:
                if id(edge) == edge_pyid:
                    tags.append(self._ensure_grip_handle(edge))
                    break

        # Fighter handle — if exactly one fighter name appears and no tag yet.
        if not tags:
            for h, entry in self._handles.items():
                if entry.kind != "fighter":
                    continue
                if entry.label in ev.description:
                    tags.append(h)
                    break

        if not tags:
            return ""
        return "  " + " ".join(f"[{t}]" for t in tags)

    def _allocate_oneshot_throw_tag(self, ev, attacker_name: str) -> str:
        """Allocate a T#NN handle for a same-tick-resolved commit (N=1 path).
        The underlying object is just the Event.data blob — we snapshot what
        we know so `inspect T#NN` still renders something useful.
        """
        handle = f"T#{self._next_throw_n:02d}"
        self._next_throw_n += 1
        snapshot = {
            "attacker":      attacker_name,
            "throw_id":      ev.data.get("throw_id", "?"),
            "compression_n": ev.data.get("compression_n", 1),
            "commit_actual": ev.data.get("actual_match", 0.0),
            "tick":          ev.tick,
        }
        self._handles[handle] = HandleEntry(
            handle=handle, kind="throw",
            label=f"{attacker_name} → {snapshot['throw_id']} (single-tick commit)",
            describe=lambda s=snapshot: _describe_throw_snapshot(s),
            alive=lambda: False,  # resolves in-tick, never lives
        )
        self._attacker_current_throw[attacker_name] = handle
        return handle

    # -----------------------------------------------------------------------
    # PAUSE / REPL
    # -----------------------------------------------------------------------
    def trigger_for(self, events: list["Event"]) -> Optional[tuple[str, "Event"]]:
        for ev in events:
            if ev.data.get("silent"):
                continue
            for category, types in PAUSE_TRIGGERS.items():
                if category not in self.pause_on:
                    continue
                if ev.event_type in types:
                    return (category, ev)
        return None

    def maybe_pause(self, tick: int, events: list["Event"]) -> None:
        if self._quit_requested:
            return
        trigger = self.trigger_for(events)
        if trigger is None:
            return
        category, ev = trigger
        self._enter_repl(tick, category, ev)

    def quit_requested(self) -> bool:
        return self._quit_requested

    def _enter_repl(self, tick: int, category: str, ev: "Event") -> None:
        sys.stdout.flush()
        print()
        print(f"-- pause @ t{tick:03d} — trigger: {category} "
              f"({ev.event_type}) --")
        while True:
            try:
                line = input("(inspect)> ").strip()
            except EOFError:
                # stdin closed (piped input) — resume silently.
                print()
                return
            except KeyboardInterrupt:
                print("\n[debug] quit requested.")
                self._quit_requested = True
                return
            if not line or line in ("c", "continue"):
                print("[debug] continuing...")
                return
            self._handle_command(line)

    def _handle_command(self, line: str) -> None:
        parts = line.split(None, 1)
        cmd = parts[0]
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("help", "?"):
            _print_repl_help()
            return
        if cmd in ("quit", "q"):
            self._quit_requested = True
            return
        if cmd in ("list", "ls"):
            self._print_handle_list(arg or None)
            return
        if cmd == "find":
            if not arg:
                print("usage: find <substring>")
                return
            self._find(arg)
            return
        if cmd == "pause-on":
            self._reconfigure_pause(arg)
            return

        # Otherwise treat the whole line as a handle (case-insensitive).
        handle = _normalize_handle(line)
        entry = self._handles.get(handle)
        if entry is None:
            print(f"[debug] unknown handle: {line!r}. Try `list` or `help`.")
            return
        print(entry.describe())
        if not entry.alive():
            print("  (expired — last-known state shown)")

    def _print_handle_list(self, kind_filter: Optional[str]) -> None:
        rows: list[tuple[str, str, str]] = []  # (handle, kind, label)
        for h, e in self._handles.items():
            if kind_filter and e.kind != kind_filter.lower().rstrip("s"):
                continue
            suffix = "" if e.alive() else " (expired)"
            rows.append((h, e.kind, e.label + suffix))
        rows.sort(key=lambda r: (r[1], r[0]))
        if not rows:
            print("[debug] (no handles)")
            return
        print(f"[debug] {len(rows)} handle(s):")
        for h, kind, label in rows:
            print(f"  {h:<6} {kind:<8} {label}")

    def _find(self, needle: str) -> None:
        needle_low = needle.lower()
        hits = [
            (h, e) for h, e in self._handles.items()
            if needle_low in e.label.lower()
        ]
        if not hits:
            print(f"[debug] no handle matches {needle!r}.")
            return
        for h, e in hits:
            print(f"  {h:<6} {e.kind:<8} {e.label}")

    def _reconfigure_pause(self, arg: str) -> None:
        if not arg:
            print(f"[debug] currently pausing on: "
                  f"{', '.join(sorted(self.pause_on)) or '(none)'}")
            print(f"[debug] available: {', '.join(sorted(PAUSE_TRIGGERS))}")
            return
        if arg in ("none", "off"):
            self.pause_on = set()
            print("[debug] auto-pause disabled.")
            return
        if arg == "all":
            self.pause_on = set(PAUSE_TRIGGERS)
            print("[debug] pausing on all triggers.")
            return
        requested = {p.strip() for p in arg.split(",") if p.strip()}
        bad = requested - set(PAUSE_TRIGGERS)
        if bad:
            print(f"[debug] unknown trigger(s): {', '.join(sorted(bad))}")
            return
        self.pause_on = requested
        print(f"[debug] now pausing on: {', '.join(sorted(requested))}")


# ===========================================================================
# HELPERS
# ===========================================================================
def _normalize_handle(raw: str) -> str:
    """Accept `G#3`, `g#3`, `G03`, `g3` — normalize to `G#03` style."""
    s = raw.strip().upper().replace(" ", "")
    if "#" not in s:
        for i, ch in enumerate(s):
            if ch.isdigit():
                s = s[:i] + "#" + s[i:]
                break
    prefix, _, num = s.partition("#")
    if num.isdigit() and prefix in ("G", "T"):
        return f"{prefix}#{int(num):02d}"
    return s


def _throw_name(throw_id) -> str:
    try:
        from throws import THROW_REGISTRY
        return THROW_REGISTRY[throw_id].name
    except Exception:
        return getattr(throw_id, "name", str(throw_id))


def _infer_attacker_from_entry(ev, match) -> Optional[str]:
    for fighter in (match.fighter_a, match.fighter_b):
        if fighter.identity.name in ev.description:
            return fighter.identity.name
    return None


def _guess_attacker_from_description(ev, match) -> Optional[str]:
    return _infer_attacker_from_entry(ev, match)


# ---------------------------------------------------------------------------
# DESCRIBERS — one per handle kind. Kept terse; calibration wants
# information density, not prose.
# ---------------------------------------------------------------------------
def _describe_fighter(fighter, match=None) -> str:
    ident = fighter.identity
    cap = fighter.capability
    state = fighter.state
    score = state.score
    lines = [
        f"{ident.name} — {ident.belt_rank.name}, "
        f"{ident.body_archetype.name}, age {ident.age}, "
        f"{ident.dominant_side.name}-dominant",
        f"  score:      waza-ari {score.get('waza_ari', 0)}   "
        f"ippon={score.get('ippon', False)}",
        f"  composure:  {state.composure_current:.2f}   "
        f"stance: {state.current_stance.name}   "
        f"stun_ticks: {state.stun_ticks}",
        f"  fight_iq:   {cap.fight_iq}   "
        f"ne_waza: {cap.ne_waza_skill}   "
        f"cardio_cap/eff: {cap.cardio_capacity}/{cap.cardio_efficiency}",
    ]
    # HAJ-35 — desperation state. Read live from match; show the signals
    # producing defensive pressure so calibration has something to aim at.
    if match is not None:
        name = ident.name
        off_active = match._offensive_desperation_active.get(name, False)
        def_active = match._defensive_desperation_active.get(name, False)
        tracker = match._defensive_pressure.get(name)
        ceiling = max(1.0, float(cap.composure_ceiling))
        comp_frac = state.composure_current / ceiling
        kumi = match.kumi_kata_clock.get(name, 0)
        lines.append(
            f"  desperation: offensive={off_active}  defensive={def_active}"
        )
        lines.append(
            f"    (offensive gate: composure_frac={comp_frac:.2f} "
            f"kumi_clock={kumi})"
        )
        if tracker is not None:
            br = tracker.breakdown(match.ticks_run)
            lines.append(
                f"    (defensive gate: score={br['score']:.1f} "
                f"opp_commits={br['opp_commits']} "
                f"kuzushi={br['kuzushi']} "
                f"comp_drop={br['composure_drop']})"
            )
    # Most-fatigued / most-injured parts to keep the dump short.
    parts = []
    for pname in ("right_hand", "left_hand", "right_leg", "left_leg",
                  "core", "lower_back"):
        ps = state.body.get(pname)
        if ps is None:
            continue
        parts.append(
            f"    {pname:<13} fatigue={ps.fatigue:.2f} "
            f"injury={ps.injury_state.name} "
            f"contact={ps.contact_state.name}"
        )
    if parts:
        lines.append("  body (key parts):")
        lines.extend(parts)
    return "\n".join(lines)


def _describe_grip(edge, match) -> str:
    lines = [
        f"grip {edge.grasper_id} ({edge.grasper_part.value}) "
        f"→ {edge.target_id} ({edge.target_location.value})",
        f"  type_v2:    {edge.grip_type_v2.name}",
        f"  depth:      {edge.depth_level.name} (modifier={edge.depth:.2f})",
        f"  mode:       {edge.mode.name}",
        f"  strength:   {edge.strength:.2f}",
        f"  contested:  {edge.contested}",
        f"  unconv_clk: {edge.unconventional_clock}",
        f"  established:t{edge.established_tick:03d}",
    ]
    if match is not None and edge not in match.grip_graph.edges:
        lines.append("  (no longer on the graph)")
    return "\n".join(lines)


def _describe_throw(tip, match) -> str:
    throw_name = _throw_name(tip.throw_id)
    offset = tip.offset(match.ticks_run) if match else 0
    lines = [
        f"throw attempt — {tip.attacker_name} → {throw_name}",
        f"  defender:       {tip.defender_name}",
        f"  started:        t{tip.start_tick:03d}",
        f"  compression_n:  {tip.compression_n}   "
        f"offset: {offset}/{tip.compression_n}",
        f"  commit_actual:  {tip.commit_actual:.3f}",
        f"  last_sub_event: "
        f"{tip.last_sub_event.name if tip.last_sub_event else '(none)'}",
    ]
    return "\n".join(lines)


def _describe_throw_snapshot(snap: dict) -> str:
    return "\n".join([
        f"throw attempt — {snap['attacker']} → {snap['throw_id']} "
        f"(resolved on t{snap['tick']:03d}, N=1 path)",
        f"  compression_n:  {snap['compression_n']}",
        f"  commit_actual:  {snap['commit_actual']:.3f}",
    ])


def _describe_referee(ref) -> str:
    return "\n".join([
        f"referee — {ref.name} ({ref.nationality})",
        f"  patience:      {ref.newaza_patience:.2f}",
        f"  strictness:    {ref.ippon_strictness:.2f}",
    ])


def _describe_match(match) -> str:
    lines = [
        f"match state — tick {match.ticks_run}/{match.max_ticks}",
        f"  sub_loop:        {match.sub_loop_state.name}",
        f"  position:        {match.position.name}",
        f"  edge_count:      {match.grip_graph.edge_count()}",
        f"  engagement_tks:  {match.engagement_ticks}",
        f"  stalemate_tks:   {match.stalemate_ticks}",
        f"  kumi_kata_clk:   "
        f"{match.fighter_a.identity.name}="
        f"{match.kumi_kata_clock[match.fighter_a.identity.name]}   "
        f"{match.fighter_b.identity.name}="
        f"{match.kumi_kata_clock[match.fighter_b.identity.name]}",
        f"  score:           "
        f"{match.fighter_a.identity.name} waza-ari="
        f"{match.fighter_a.state.score['waza_ari']}   "
        f"{match.fighter_b.identity.name} waza-ari="
        f"{match.fighter_b.state.score['waza_ari']}",
    ]
    if match.osaekomi.active:
        lines.append(
            f"  osaekomi:        active, holder={match.osaekomi.holder_id}, "
            f"elapsed={match.osaekomi.elapsed_ticks}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# REPL HELP
# ---------------------------------------------------------------------------
def _print_repl_help() -> None:
    print(
        "[debug] inspector commands:\n"
        "  <handle>            expand a handle (e.g. G#03, F#A, T#01, M#1, R#1)\n"
        "  list [kind]         list all handles (optional: fighter|grip|throw|ref|match)\n"
        "  find <text>         search handle labels\n"
        "  pause-on [spec]     show or change pause triggers\n"
        "                        spec: `all`, `none`, or CSV of "
        "throw,score,kuzushi,matte,ne_waza,shido\n"
        "  help | ?            this help\n"
        "  quit | q            abort the match\n"
        "  (blank) | c         continue to next trigger\n"
        "\n"
        "handle conventions:\n"
        "  F#A, F#B  fighters (stable for the match)\n"
        "  G#NN      grip edges (assigned when first seen, survive past removal)\n"
        "  T#NN      throw attempts (one per commit)\n"
        "  R#1       referee\n"
        "  M#1       match-level state (position, clocks, scores, osaekomi)\n"
    )
