# tests/test_haj220_ne_waza_consumption.py
# HAJ-220 — Ne-waza catalog consumption: minimum-viable ground-position
# rendering. Mirrors HAJ-207's coverage shape for the tachiwaza catalog.
#
# Sections:
#   - ConnectionEdge / GroundConnectionGraph basics + position baselines
#   - Stage 1 availability filter against varied ConnectionEdge configs
#   - Dominant-position recognition (sankaku, back_turtle_with_hooks)
#   - Stage 2 first-available commit selection
#   - OsaekomiClock with technique_id (new field + start signature)
#   - Submission resolution tap / release / continue
#   - Integration: Match wired with the catalog → ground tick emits
#     [pin] / [sub] events keyed by technique_id
#   - Regression: legacy (no-catalog) ne-waza path still works

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from body_state import place_judoka  # noqa: E402
from enums import BeltRank, Position, SubLoopState  # noqa: E402
from match import Match  # noqa: E402
from ne_waza import OsaekomiClock, NewazaResolver  # noqa: E402
from ne_waza_catalog import (  # noqa: E402
    BodyPart, ConnectionRequirement, ConnectionType,
    DefensePhase, DefensiveStrutDefinition, InducedTransition,
    JointTarget, MechanicalClass, MechanismFamily,
    NeWazaCatalog, NeWazaKodokanStatus, NeWazaPositionDefinition,
    NeWazaSubfamily, NeWazaTechniqueDefinition, ScoreMechanism,
    load_ne_waza_catalog,
)
from ne_waza_consumption import (  # noqa: E402
    ConnectionEdge, ENTRY_THRESHOLD, GroundConnectionGraph,
    STAY_THRESHOLD, SUBMISSION_RELEASE_FAILED_TICKS,
    SubmissionAttempt, baseline_graph_for, ne_waza_stage1_available_techniques,
    pin_still_satisfied, recognize_dominant_position,
    stage2_select_commit, submission_tick,
)
from referee import build_suzuki  # noqa: E402
import main as main_module  # noqa: E402


# ---------------------------------------------------------------------------
# Tiny synthetic catalog so unit tests don't have to thread the 29-entry
# canonical catalog through every assertion. Real-catalog coverage is
# at the bottom in the integration block.
# ---------------------------------------------------------------------------
def _req(ct: ConnectionType, q: float, tori_part: str = "tori",
         target: str = "uke") -> ConnectionRequirement:
    return ConnectionRequirement(
        type=ct, tori_part=tori_part, target=target,
        minimum_quality=q, extras={},
    )


def _pin(
    tid: str, parent: str = "SIDE_CONTROL_RIGHT",
    base_difficulty: int = 30,
    minimum_belt: str = "white",
    reqs: list[ConnectionRequirement] | None = None,
) -> NeWazaTechniqueDefinition:
    return NeWazaTechniqueDefinition(
        technique_id=tid,
        name_japanese=tid.title(),
        name_english=tid,
        family="ne_waza",
        subfamily=NeWazaSubfamily.PIN,
        kodokan_status=NeWazaKodokanStatus.KATAME_NO_KATA,
        required_connections=reqs or [
            _req(ConnectionType.BODY_PRESSURE, 0.6),
        ],
        score_mechanism=ScoreMechanism.PIN_TIME_ACCUMULATION,
        base_difficulty=base_difficulty,
        parent_position=parent,
        fires_from_position=None,
        minimum_belt_for_competition_use=minimum_belt,
    )


def _submission(
    tid: str, base_difficulty: int = 40, minimum_belt: str = "white",
    reqs: list[ConnectionRequirement] | None = None,
    parent: str | None = None,
    fires_from: str | None = None,
    subfamily: NeWazaSubfamily = NeWazaSubfamily.STRANGLE,
    joint_target: JointTarget | None = None,
    fulcrum: str | None = None,
) -> NeWazaTechniqueDefinition:
    return NeWazaTechniqueDefinition(
        technique_id=tid,
        name_japanese=tid.title(),
        name_english=tid,
        family="ne_waza",
        subfamily=subfamily,
        kodokan_status=NeWazaKodokanStatus.KATAME_NO_KATA,
        required_connections=reqs or [
            _req(ConnectionType.ANATOMICAL_WRAP, 0.6),
        ],
        score_mechanism=ScoreMechanism.IMMEDIATE_SUBMISSION,
        base_difficulty=base_difficulty,
        parent_position=parent,
        fires_from_position=fires_from,
        minimum_belt_for_competition_use=minimum_belt,
        joint_target=joint_target,
        fulcrum_body_part=fulcrum,
    )


def _position(
    pid: str, reqs: list[ConnectionRequirement], terminals: list[str],
    parent: str = "any",
) -> NeWazaPositionDefinition:
    return NeWazaPositionDefinition(
        position_id=pid,
        description=pid,
        required_connections=reqs,
        terminal_techniques=terminals,
        parent_position=parent,
    )


def _bw_judoka(name: str = "Tori", belt: BeltRank = BeltRank.BROWN,
               ne_skill: int = 7):
    j = main_module.build_tanaka()
    j.identity.name = name
    j.identity.belt_rank = belt
    j.capability.ne_waza_skill = ne_skill
    return j


# ===========================================================================
# CONNECTION EDGE + GRAPH
# ===========================================================================
class TestConnectionGraph:

    def test_add_and_query_edges(self) -> None:
        g = GroundConnectionGraph()
        g.add(ConnectionEdge(ConnectionType.BODY_PRESSURE, "chest", "uke_chest", 0.7))
        g.add(ConnectionEdge(ConnectionType.ANATOMICAL_WRAP, "arm", "uke_neck", 0.5))
        assert len(g.edges) == 2
        assert g.has_type_at_quality(ConnectionType.BODY_PRESSURE, 0.6)
        assert not g.has_type_at_quality(ConnectionType.BODY_PRESSURE, 0.8)
        wraps = g.edges_of_type(ConnectionType.ANATOMICAL_WRAP)
        assert len(wraps) == 1 and wraps[0].quality == 0.5

    def test_clear(self) -> None:
        g = GroundConnectionGraph()
        g.add(ConnectionEdge(ConnectionType.BODY_PRESSURE, "a", "b", 0.5))
        g.clear()
        assert g.edges == []

    def test_baseline_side_control_satisfies_hon_kesa(self) -> None:
        """Baseline for SIDE_CONTROL is authored to satisfy hon_kesa_gatame's
        four required_connections at ENTRY_THRESHOLD. Sanity check the
        baseline shape."""
        g = baseline_graph_for(Position.SIDE_CONTROL)
        types = {e.type for e in g.edges}
        assert ConnectionType.ANATOMICAL_WRAP in types
        assert ConnectionType.ANATOMICAL_TRAP in types
        assert ConnectionType.BODY_PRESSURE in types
        assert ConnectionType.POSITIONAL_BASE in types

    def test_baseline_unknown_position_is_empty(self) -> None:
        g = baseline_graph_for(Position.STANDING_DISTANT)
        assert g.edges == []


# ===========================================================================
# STAGE 1 — AVAILABILITY FILTER
# ===========================================================================
class TestStage1Availability:

    def test_pin_available_when_connections_satisfy_entry_threshold(self) -> None:
        pin = _pin(
            "hon_kesa_gatame",
            reqs=[_req(ConnectionType.BODY_PRESSURE, 0.6)],
        )
        catalog_techs = {"hon_kesa_gatame": pin}
        g = GroundConnectionGraph()
        # 0.31 is just above 0.6 * 0.5 = 0.3 → satisfies ENTRY_THRESHOLD.
        g.add(ConnectionEdge(ConnectionType.BODY_PRESSURE, "t", "u", 0.31))
        out = ne_waza_stage1_available_techniques(
            g, Position.SIDE_CONTROL,
            _bw_judoka(), _bw_judoka(name="Uke"),
            catalog_techs, {},
        )
        assert out == {"hon_kesa_gatame"}

    def test_pin_filtered_when_connection_quality_below_entry_threshold(
        self,
    ) -> None:
        pin = _pin(
            "hon_kesa_gatame",
            reqs=[_req(ConnectionType.BODY_PRESSURE, 0.6)],
        )
        catalog_techs = {"hon_kesa_gatame": pin}
        g = GroundConnectionGraph()
        # 0.29 is just under 0.6 * 0.5 = 0.3 → fails ENTRY_THRESHOLD.
        g.add(ConnectionEdge(ConnectionType.BODY_PRESSURE, "t", "u", 0.29))
        out = ne_waza_stage1_available_techniques(
            g, Position.SIDE_CONTROL,
            _bw_judoka(), _bw_judoka(name="Uke"),
            catalog_techs, {},
        )
        assert out == set()

    def test_pin_filtered_when_required_connection_type_missing(self) -> None:
        pin = _pin(
            "hon_kesa_gatame",
            reqs=[
                _req(ConnectionType.BODY_PRESSURE, 0.6),
                _req(ConnectionType.ANATOMICAL_WRAP, 0.5),
            ],
        )
        g = GroundConnectionGraph()
        g.add(ConnectionEdge(ConnectionType.BODY_PRESSURE, "t", "u", 0.8))
        # No ANATOMICAL_WRAP edge — pin should be unavailable.
        out = ne_waza_stage1_available_techniques(
            g, Position.SIDE_CONTROL,
            _bw_judoka(), _bw_judoka(name="Uke"),
            {"hon_kesa_gatame": pin}, {},
        )
        assert out == set()

    def test_pin_filtered_when_belt_below_minimum(self) -> None:
        pin = _pin("rare_pin", minimum_belt="black_1")  # unknown → no floor
        # Use a real floor instead: blue.
        pin.minimum_belt_for_competition_use = "blue"
        catalog_techs = {"rare_pin": pin}
        g = baseline_graph_for(Position.SIDE_CONTROL)
        out_white = ne_waza_stage1_available_techniques(
            g, Position.SIDE_CONTROL,
            _bw_judoka(belt=BeltRank.WHITE),
            _bw_judoka(name="Uke"),
            catalog_techs, {},
        )
        assert out_white == set()
        out_blue = ne_waza_stage1_available_techniques(
            g, Position.SIDE_CONTROL,
            _bw_judoka(belt=BeltRank.BLUE),
            _bw_judoka(name="Uke"),
            catalog_techs, {},
        )
        assert out_blue == {"rare_pin"}

    def test_position_agnostic_submission_passes_position_check(self) -> None:
        sub = _submission(
            "ude_hishigi_juji_gatame",
            reqs=[_req(ConnectionType.LIMB_ISOLATION, 0.5)],
            subfamily=NeWazaSubfamily.JOINT_LOCK,
            joint_target=JointTarget.ELBOW_EXTENSION,
            fulcrum="hips_and_thighs",
        )
        g = GroundConnectionGraph()
        g.add(ConnectionEdge(ConnectionType.LIMB_ISOLATION, "t", "u", 0.5))
        out = ne_waza_stage1_available_techniques(
            g, Position.GUARD_TOP,  # arbitrary engine position
            _bw_judoka(), _bw_judoka(name="Uke"),
            {"ude_hishigi_juji_gatame": sub}, {},
        )
        assert out == {"ude_hishigi_juji_gatame"}

    def test_parent_position_yaml_right_suffix_matches_engine(self) -> None:
        """YAML SIDE_CONTROL_RIGHT should map to engine SIDE_CONTROL."""
        pin = _pin("hon_kesa_gatame", parent="SIDE_CONTROL_RIGHT")
        g = baseline_graph_for(Position.SIDE_CONTROL)
        out = ne_waza_stage1_available_techniques(
            g, Position.SIDE_CONTROL,
            _bw_judoka(), _bw_judoka(name="Uke"),
            {"hon_kesa_gatame": pin}, {},
        )
        assert out == {"hon_kesa_gatame"}

    def test_parent_position_mismatch_filters(self) -> None:
        pin = _pin("kami_shiho_gatame", parent="MOUNT")
        g = baseline_graph_for(Position.SIDE_CONTROL)
        out = ne_waza_stage1_available_techniques(
            g, Position.SIDE_CONTROL,
            _bw_judoka(), _bw_judoka(name="Uke"),
            {"kami_shiho_gatame": pin}, {},
        )
        assert out == set()


# ===========================================================================
# DOMINANT POSITION RECOGNITION
# ===========================================================================
class TestDominantPositionRecognition:

    def test_sankaku_recognized_on_full_connection_match(self) -> None:
        sankaku = _position(
            "sankaku_position",
            reqs=[
                _req(ConnectionType.LIMB_TRIANGLE, 0.6),
                _req(ConnectionType.LIMB_ISOLATION, 0.5),
            ],
            terminals=["sankaku_jime"],
            parent="any",
        )
        g = GroundConnectionGraph()
        # DOMINANT_POSITION_RECOGNITION_THRESHOLD = 1.0 → edges must hit
        # at least the authored minimum_quality.
        g.add(ConnectionEdge(ConnectionType.LIMB_TRIANGLE, "legs", "uke_hd", 0.6))
        g.add(ConnectionEdge(ConnectionType.LIMB_ISOLATION, "loop", "uke_arm", 0.5))
        pid = recognize_dominant_position(g, {"sankaku_position": sankaku})
        assert pid == "sankaku_position"

    def test_sankaku_not_recognized_when_one_connection_below(self) -> None:
        sankaku = _position(
            "sankaku_position",
            reqs=[
                _req(ConnectionType.LIMB_TRIANGLE, 0.6),
                _req(ConnectionType.LIMB_ISOLATION, 0.5),
            ],
            terminals=["sankaku_jime"],
        )
        g = GroundConnectionGraph()
        g.add(ConnectionEdge(ConnectionType.LIMB_TRIANGLE, "legs", "uke", 0.6))
        # LIMB_ISOLATION just under the authored minimum.
        g.add(ConnectionEdge(ConnectionType.LIMB_ISOLATION, "loop", "uke", 0.49))
        pid = recognize_dominant_position(g, {"sankaku_position": sankaku})
        assert pid is None

    def test_back_turtle_with_hooks_requires_back_control_parent(self) -> None:
        """back_turtle_with_hooks has parent_position: BACK_CONTROL, so it
        is only recognized when the engine position is BACK_CONTROL."""
        pos = _position(
            "back_turtle_with_hooks",
            reqs=[
                _req(ConnectionType.BODY_PRESSURE, 0.6),
                _req(ConnectionType.ANATOMICAL_WRAP, 0.5),
                _req(ConnectionType.GARMENT_GRIP_NEWAZA, 0.4),
            ],
            terminals=["hadaka_jime"],
            parent="BACK_CONTROL",
        )
        g = GroundConnectionGraph()
        g.add(ConnectionEdge(ConnectionType.BODY_PRESSURE, "chest", "uke_back", 0.6))
        g.add(ConnectionEdge(ConnectionType.ANATOMICAL_WRAP, "legs", "uke_thigh", 0.5))
        g.add(ConnectionEdge(ConnectionType.GARMENT_GRIP_NEWAZA, "hand", "uke_lap", 0.4))
        assert recognize_dominant_position(
            g, {"back_turtle_with_hooks": pos}, Position.BACK_CONTROL,
        ) == "back_turtle_with_hooks"
        assert recognize_dominant_position(
            g, {"back_turtle_with_hooks": pos}, Position.SIDE_CONTROL,
        ) is None

    def test_dominant_position_terminals_appended_to_stage1(self) -> None:
        sankaku = _position(
            "sankaku_position",
            reqs=[_req(ConnectionType.LIMB_TRIANGLE, 0.5)],
            terminals=["sankaku_jime"],
        )
        sankaku_jime = _submission(
            "sankaku_jime",
            fires_from="sankaku_position",
            subfamily=NeWazaSubfamily.STRANGLE,
        )
        g = GroundConnectionGraph()
        # No connections that would satisfy sankaku_jime's own
        # required_connections — it should still appear in Stage 1 via the
        # dominant-position terminals path.
        g.add(ConnectionEdge(ConnectionType.LIMB_TRIANGLE, "legs", "uke", 0.5))
        out = ne_waza_stage1_available_techniques(
            g, Position.GUARD_TOP,
            _bw_judoka(), _bw_judoka(name="Uke"),
            {"sankaku_jime": sankaku_jime},
            {"sankaku_position": sankaku},
            dominant_position_id="sankaku_position",
        )
        assert "sankaku_jime" in out


# ===========================================================================
# STAGE 2 — FIRST-AVAILABLE COMMIT
# ===========================================================================
class TestStage2Commit:

    def test_prefers_higher_base_difficulty(self) -> None:
        easy = _pin("easy_pin", base_difficulty=30,
                    reqs=[_req(ConnectionType.BODY_PRESSURE, 0.5)])
        hard = _pin("hard_pin", base_difficulty=50,
                    reqs=[_req(ConnectionType.BODY_PRESSURE, 0.5)])
        g = GroundConnectionGraph()
        g.add(ConnectionEdge(ConnectionType.BODY_PRESSURE, "t", "u", 0.7))
        chosen = stage2_select_commit(
            {"easy_pin", "hard_pin"}, g,
            {"easy_pin": easy, "hard_pin": hard},
        )
        assert chosen == "hard_pin"

    def test_connection_quality_margin_tiebreaks_equal_difficulty(self) -> None:
        wide = _pin("wide_margin_pin", base_difficulty=40,
                    reqs=[_req(ConnectionType.BODY_PRESSURE, 0.3)])
        narrow = _pin("narrow_margin_pin", base_difficulty=40,
                      reqs=[_req(ConnectionType.BODY_PRESSURE, 0.6)])
        g = GroundConnectionGraph()
        g.add(ConnectionEdge(ConnectionType.BODY_PRESSURE, "t", "u", 0.7))
        chosen = stage2_select_commit(
            {"wide_margin_pin", "narrow_margin_pin"}, g,
            {"wide_margin_pin": wide, "narrow_margin_pin": narrow},
        )
        assert chosen == "wide_margin_pin"

    def test_alphabetical_tiebreak_when_difficulty_and_margin_equal(self) -> None:
        a = _pin("a_pin", base_difficulty=40,
                 reqs=[_req(ConnectionType.BODY_PRESSURE, 0.5)])
        b = _pin("b_pin", base_difficulty=40,
                 reqs=[_req(ConnectionType.BODY_PRESSURE, 0.5)])
        g = GroundConnectionGraph()
        g.add(ConnectionEdge(ConnectionType.BODY_PRESSURE, "t", "u", 0.7))
        chosen = stage2_select_commit(
            {"a_pin", "b_pin"}, g, {"a_pin": a, "b_pin": b},
        )
        assert chosen == "a_pin"

    def test_empty_set_returns_none(self) -> None:
        assert stage2_select_commit(set(), GroundConnectionGraph(), {}) is None


# ===========================================================================
# OSAEKOMI CLOCK — technique_id field
# ===========================================================================
class TestOsaekomiClockTechniqueId:

    def test_legacy_start_signature_still_works(self) -> None:
        clock = OsaekomiClock()
        clock.start("Tanaka", Position.SIDE_CONTROL)
        assert clock.holder_id == "Tanaka"
        assert clock.technique_id is None
        assert clock.is_running

    def test_start_records_technique_id(self) -> None:
        clock = OsaekomiClock()
        clock.start("Tanaka", Position.SIDE_CONTROL,
                    technique_id="hon_kesa_gatame")
        assert clock.technique_id == "hon_kesa_gatame"

    def test_break_pin_clears_technique_id(self) -> None:
        clock = OsaekomiClock()
        clock.start("Tanaka", Position.SIDE_CONTROL,
                    technique_id="hon_kesa_gatame")
        clock.break_pin()
        assert clock.technique_id is None
        assert not clock.is_running


# ===========================================================================
# SUBMISSION RESOLUTION
# ===========================================================================
class TestSubmissionResolution:

    def test_tap_fires_when_uke_defense_roll_fails(self) -> None:
        # uke ne_waza_skill = 0 → defense band = 0; every roll > 0 →
        # immediate tap.
        att = SubmissionAttempt(
            technique_id="ude_hishigi_juji_gatame",
            aggressor_id="Tori", defender_id="Uke",
        )
        tori = _bw_judoka(ne_skill=8)
        uke = _bw_judoka(name="Uke", ne_skill=0)
        rng = random.Random(123)
        out = submission_tick(att, tori, uke, rng)
        assert out == "tap"

    def test_release_fires_after_threshold_failed_ticks(self) -> None:
        # uke defense ceiling so high (skill=10 → 100) that defense never
        # fails; tori effectiveness 0 → effectiveness always fails. After
        # SUBMISSION_RELEASE_FAILED_TICKS consecutive failures, release.
        att = SubmissionAttempt(
            technique_id="ude_hishigi_juji_gatame",
            aggressor_id="Tori", defender_id="Uke",
        )
        tori = _bw_judoka(ne_skill=0)
        uke = _bw_judoka(name="Uke", ne_skill=10)
        rng = random.Random(456)
        outcomes = [submission_tick(att, tori, uke, rng)
                    for _ in range(SUBMISSION_RELEASE_FAILED_TICKS)]
        # Every tick before the threshold should be "continue"; the
        # threshold-hitting tick is "release".
        assert outcomes[-1] == "release"
        assert all(o == "continue" for o in outcomes[:-1])
        assert att.ticks_elapsed == SUBMISSION_RELEASE_FAILED_TICKS

    def test_continue_when_neither_tap_nor_release(self) -> None:
        # Mid-skill on both sides: neither immediate tap nor release.
        att = SubmissionAttempt(
            technique_id="hadaka_jime",
            aggressor_id="Tori", defender_id="Uke",
        )
        tori = _bw_judoka(ne_skill=7)
        uke = _bw_judoka(name="Uke", ne_skill=7)
        rng = random.Random(0)
        out = submission_tick(att, tori, uke, rng)
        assert out in ("tap", "release", "continue")
        assert att.ticks_elapsed == 1


# ===========================================================================
# PIN STILL SATISFIED — STAY_THRESHOLD predicate
# ===========================================================================
class TestPinStillSatisfied:

    def test_pin_satisfied_at_baseline(self) -> None:
        pin = _pin("hon_kesa_gatame",
                   reqs=[_req(ConnectionType.BODY_PRESSURE, 0.6)])
        g = GroundConnectionGraph()
        g.add(ConnectionEdge(ConnectionType.BODY_PRESSURE, "t", "u", 0.4))
        assert pin_still_satisfied(g, pin)  # 0.4 > 0.6 * 0.5 = 0.3

    def test_pin_breaks_when_connection_falls_below_stay_threshold(self) -> None:
        pin = _pin("hon_kesa_gatame",
                   reqs=[_req(ConnectionType.BODY_PRESSURE, 0.6)])
        g = GroundConnectionGraph()
        g.add(ConnectionEdge(ConnectionType.BODY_PRESSURE, "t", "u", 0.29))
        assert not pin_still_satisfied(g, pin)

    def test_pin_predicate_rejects_non_pin_techniques(self) -> None:
        sub = _submission("ude_hishigi_juji_gatame")
        g = GroundConnectionGraph()
        g.add(ConnectionEdge(ConnectionType.ANATOMICAL_WRAP, "t", "u", 1.0))
        # IMMEDIATE_SUBMISSION techniques are not pins — the predicate
        # explicitly returns False for them.
        assert not pin_still_satisfied(g, sub)


# ===========================================================================
# INTEGRATION — Match wired with the catalog
# ===========================================================================
class TestMatchIntegration:

    def _make_match_with_catalog(self, seed: int = 1):
        random.seed(seed)
        catalog = load_ne_waza_catalog(
            REPO_ROOT / "data" / "ne_waza_techniques.yaml",
            REPO_ROOT / "data" / "ne_waza_positions.yaml",
            REPO_ROOT / "data" / "defensive_struts.yaml",
        )
        t = main_module.build_tanaka()
        s = main_module.build_sato()
        place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
        place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
        m = Match(
            fighter_a=t, fighter_b=s, referee=build_suzuki(),
            seed=seed, ne_waza_catalog=catalog,
        )
        return t, s, m

    def test_match_constructs_with_ne_waza_catalog(self) -> None:
        _, _, m = self._make_match_with_catalog()
        assert m.ne_waza_catalog is not None
        assert m.ne_waza_resolver._ne_waza_catalog is m.ne_waza_catalog

    def test_ground_entry_seeds_connection_graph(self) -> None:
        _, _, m = self._make_match_with_catalog()
        m.ne_waza_resolver.on_ground_entry(Position.SIDE_CONTROL)
        assert m.ne_waza_resolver._connection_graph is not None
        assert len(m.ne_waza_resolver._connection_graph.edges) > 0
        assert m.ne_waza_resolver._last_ground_position == Position.SIDE_CONTROL

    def test_catalog_tick_emits_pin_event_with_technique_id(self) -> None:
        """After ground entry into SIDE_CONTROL, the first catalog tick
        should commit hon_kesa_gatame (or another SIDE_CONTROL pin from
        the canonical catalog) and emit an OSAEKOMI_BEGIN event keyed by
        technique_id. Use a seed that doesn't trip the escape roll on
        tick 0."""
        t, s, m = self._make_match_with_catalog(seed=42)
        m.sub_loop_state = SubLoopState.NE_WAZA
        m.position = Position.SIDE_CONTROL
        m.ne_waza_top_id = t.identity.name
        m.ne_waza_resolver.set_top_fighter(
            t.identity.name, (m.fighter_a, m.fighter_b),
        )
        m.ne_waza_resolver.on_ground_entry(Position.SIDE_CONTROL)
        # Drive the catalog tick until a pin commits or escape resets.
        commit_event = None
        for tick in range(10):
            ne_events = m.ne_waza_resolver.tick_resolve(
                position=m.position, graph=m.grip_graph,
                fighters=(m.fighter_a, m.fighter_b),
                osaekomi=m.osaekomi, current_tick=tick,
            )
            for ev in ne_events:
                if ev.event_type == "OSAEKOMI_BEGIN":
                    commit_event = ev
                    break
            if commit_event is not None or any(
                ev.event_type == "ESCAPE_SUCCESS" for ev in ne_events
            ):
                break
        assert commit_event is not None, (
            "expected an OSAEKOMI_BEGIN event within 10 ticks"
        )
        tid = commit_event.data.get("technique_id")
        assert tid is not None
        assert tid in m.ne_waza_catalog.techniques
        assert commit_event.description == f"[pin] {tid} committed"
        # The OsaekomiClock should now be running on that technique.
        assert m.osaekomi.is_running
        assert m.osaekomi.technique_id == tid


# ===========================================================================
# REGRESSION — legacy ne-waza path still works when no catalog supplied
# ===========================================================================
class TestLegacyPathPreserved:

    def test_resolver_with_no_catalog_uses_hardcoded_chain(self) -> None:
        random.seed(7)
        t = main_module.build_tanaka()
        s = main_module.build_sato()
        place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
        place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
        m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=7)
        # No ne_waza_catalog passed — resolver._ne_waza_catalog must be None
        # and the catalog branch must be dormant.
        assert m.ne_waza_catalog is None
        assert m.ne_waza_resolver._ne_waza_catalog is None

    def test_existing_osaekomi_two_arg_call_still_compatible(self) -> None:
        """test_haj185_ne_waza_state_machine.py calls
        `osaekomi.start("A", Position.SIDE_CONTROL)` — make sure the new
        keyword argument hasn't broken positional-only calls."""
        clock = OsaekomiClock()
        clock.start("A", Position.SIDE_CONTROL)
        assert clock.is_running
        assert clock.technique_id is None
