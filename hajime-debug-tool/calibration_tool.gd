# calibration_tool.gd
# Attach this to the CalibrationTool root node.
# It populates dropdowns, gathers UI state into JSON, runs the Python
# simulation as a subprocess, and renders the resulting event log.

extends Control

# ============================================================
# Configuration (edit these for your machine if needed)
# ============================================================
const PYTHON_EXECUTABLE := "python"
const RUN_MATCH_SCRIPT := "C:/Users/jackc/hajime/src/run_match.py"
const CONFIG_PATH := "user://hajime_match_config.json"
const OUTPUT_PATH := "user://hajime_match_log.json"
const SAVED_CONFIG_PATH := "user://saved_config.json"

# ============================================================
# Dropdown options
# ============================================================
const WEIGHT_CLASSES := ["-90kg"]
const BODY_ARCHETYPES := ["LEVER", "MOTOR", "GRIP_FIGHTER", "GROUND_SPECIALIST", "EXPLOSIVE"]
const BELTS := ["WHITE", "YELLOW", "ORANGE", "GREEN", "BLUE", "BROWN",
				"BLACK_1", "BLACK_2", "BLACK_3", "BLACK_4", "BLACK_5"]
const DOMINANT_SIDES := ["RIGHT", "LEFT"]
const STARTING_POSITIONS := ["STANDING_NEUTRAL", "STANDING_GRIPPED", "GROUND_NEUTRAL",
							 "GROUND_TOP_FIGHTER1", "GROUND_TOP_FIGHTER2"]
const FORCED_THROWS := ["NONE", "SEOI_NAGE", "O_SOTO_GARI", "UCHI_MATA", "TAI_OTOSHI"]
const REF_PERSONALITIES := ["GENEROUS", "STRICT", "NEUTRAL"]
const PRESETS := ["(none)", "Elite Mirror", "Novice Mirror",
				  "Asymmetric (Elite vs Novice)", "High-Disguise vs Elite"]

# ============================================================
# Node references
# ============================================================
@onready var fighter1_panel: VBoxContainer = $Root/TopRow/Fighter1Panel
@onready var fighter2_panel: VBoxContainer = $Root/TopRow/Fighter2Panel
@onready var match_panel: VBoxContainer = $Root/TopRow/MatchPanel
@onready var log_output: RichTextLabel = $Root/LogOutput
@onready var preset_selector: OptionButton = $Root/ButtonRow/PresetSelector

# ============================================================
# Lifecycle
# ============================================================
func _ready() -> void:
	_populate_dropdowns()
	log_output.text = "Ready. Configure both fighters, then click Run Match."

func _populate_dropdowns() -> void:
	for panel in [fighter1_panel, fighter2_panel]:
		_fill(panel.get_node("WeightClassField"), WEIGHT_CLASSES)
		_fill(panel.get_node("BodyArchetypeField"), BODY_ARCHETYPES)
		_fill(panel.get_node("BeltField"), BELTS)
		_fill(panel.get_node("DominantSideField"), DOMINANT_SIDES)
	_fill(match_panel.get_node("StartingPositionField"), STARTING_POSITIONS)
	_fill(match_panel.get_node("ForcedThrowField"), FORCED_THROWS)
	_fill(match_panel.get_node("RefPersonalityField"), REF_PERSONALITIES)
	_fill(preset_selector, PRESETS)

func _fill(option_button: OptionButton, items: Array) -> void:
	option_button.clear()
	for item in items:
		option_button.add_item(item)

# ============================================================
# Reading the UI into a config Dictionary
# ============================================================
func _build_full_config() -> Dictionary:
	return {
		"fighter1": _read_fighter(fighter1_panel),
		"fighter2": _read_fighter(fighter2_panel),
		"match": _read_match(),
	}

func _read_fighter(panel: VBoxContainer) -> Dictionary:
	return {
		"name": panel.get_node("NameField").text,
		"age": int(panel.get_node("AgeField").value),
		"height_cm": int(panel.get_node("HeightField").value),
		"weight_class": _selected_text(panel.get_node("WeightClassField")),
		"body_archetype": _selected_text(panel.get_node("BodyArchetypeField")),
		"belt_rank": _selected_text(panel.get_node("BeltField")),
		"dominant_side": _selected_text(panel.get_node("DominantSideField")),
		"personality_facets": {
			"aggressive_patient": panel.get_node("AggressivePatientSlider").value,
			"technical_athletic": panel.get_node("TechnicalAthleticSlider").value,
			"confident_anxious": panel.get_node("ConfidentAnxiousSlider").value,
			"loyal_improv": panel.get_node("LoyalImprovSlider").value,
		},
		"capability": {
			"hands_left": panel.get_node("HandsLeftSlider").value,
			"hands_right": panel.get_node("HandsRightSlider").value,
			"forearms_left": panel.get_node("ForearmsLeftSlider").value,
			"forearms_right": panel.get_node("ForearmsRightSlider").value,
			"legs_left": panel.get_node("LegsLeftSlider").value,
			"legs_right": panel.get_node("LegsRightSlider").value,
			"core": panel.get_node("CoreSlider").value,
			"lower_back": panel.get_node("LowerBackSlider").value,
			"neck": panel.get_node("NeckSlider").value,
			"cardio_capacity": panel.get_node("CardioCapacitySlider").value,
			"cardio_efficiency": panel.get_node("CardioEfficiencySlider").value,
			"fight_iq": panel.get_node("FightIQSlider").value,
			"composure_ceiling": panel.get_node("ComposureCeilingSlider").value,
			"ne_waza_skill": panel.get_node("NeWazaSkillSlider").value,
			"other_body_parts_global": panel.get_node("OtherBodyPartsGlobalSlider").value,
		},
	}

func _read_match() -> Dictionary:
	return {
		"starting_position": _selected_text(match_panel.get_node("StartingPositionField")),
		"time_on_clock": int(match_panel.get_node("TimeOnClockField").value),
		"forced_throw": _selected_text(match_panel.get_node("ForcedThrowField")),
		"ref_personality": _selected_text(match_panel.get_node("RefPersonalityField")),
	}

func _selected_text(option_button: OptionButton) -> String:
	var idx := option_button.selected
	if idx < 0:
		return ""
	return option_button.get_item_text(idx)

# ============================================================
# Run Match
# ============================================================
func _on_run_match_button_pressed() -> void:
	var config := _build_full_config()
	var config_path_abs := ProjectSettings.globalize_path(CONFIG_PATH)
	var output_path_abs := ProjectSettings.globalize_path(OUTPUT_PATH)

	# Write config JSON
	var f := FileAccess.open(CONFIG_PATH, FileAccess.WRITE)
	if f == null:
		log_output.text = "ERROR: Could not write config file: %s" % config_path_abs
		return
	f.store_string(JSON.stringify(config, "  "))
	f.close()

	log_output.text = "Running match...\n(This blocks the UI; long matches will pause Godot.)\n"

	# Run Python subprocess (synchronous)
	var args := [
		RUN_MATCH_SCRIPT,
		"--config", config_path_abs,
		"--output", output_path_abs,
	]
	var stdout: Array = []
	var exit_code := OS.execute(PYTHON_EXECUTABLE, args, stdout, true)

	if exit_code != 0:
		log_output.text = "ERROR: Python exited with code %d\n\nOutput:\n%s" % [
			exit_code, "\n".join(stdout)
		]
		return

	# Read output JSON
	var out := FileAccess.open(OUTPUT_PATH, FileAccess.READ)
	if out == null:
		log_output.text = "ERROR: No output file at: %s" % output_path_abs
		return
	var output_text := out.get_as_text()
	out.close()

	var parsed = JSON.parse_string(output_text)
	if parsed == null:
		log_output.text = "ERROR: Could not parse output JSON.\n\nRaw output:\n" + output_text
		return

	_render_log(parsed)

func _render_log(log_data) -> void:
	log_output.clear()
	var events: Array = []
	if log_data is Array:
		events = log_data
	elif log_data is Dictionary and log_data.has("events"):
		events = log_data["events"]
	else:
		log_output.append_text(JSON.stringify(log_data, "  "))
		return

	for event in events:
		log_output.append_text(_format_event(event))
		log_output.append_text("\n")

func _format_event(event: Dictionary) -> String:
	var tick = event.get("tick", "?")
	var event_type = event.get("type", "EVENT")
	var prose = event.get("prose", JSON.stringify(event))
	return "[t=%s] [%s] %s" % [str(tick), str(event_type), str(prose)]

# ============================================================
# Save / Load
# ============================================================
func _on_save_button_pressed() -> void:
	var config := _build_full_config()
	var f := FileAccess.open(SAVED_CONFIG_PATH, FileAccess.WRITE)
	if f == null:
		log_output.text = "ERROR: Could not save config."
		return
	f.store_string(JSON.stringify(config, "  "))
	f.close()
	log_output.text = "Config saved to: %s" % ProjectSettings.globalize_path(SAVED_CONFIG_PATH)

func _on_load_button_pressed() -> void:
	if not FileAccess.file_exists(SAVED_CONFIG_PATH):
		log_output.text = "No saved config at: %s" % ProjectSettings.globalize_path(SAVED_CONFIG_PATH)
		return
	var f := FileAccess.open(SAVED_CONFIG_PATH, FileAccess.READ)
	var text := f.get_as_text()
	f.close()
	var config = JSON.parse_string(text)
	if config == null:
		log_output.text = "ERROR: Could not parse saved config."
		return
	_apply_config(config)
	log_output.text = "Config loaded from: %s" % ProjectSettings.globalize_path(SAVED_CONFIG_PATH)

func _apply_config(config: Dictionary) -> void:
	if config.has("fighter1"):
		_apply_fighter(fighter1_panel, config["fighter1"])
	if config.has("fighter2"):
		_apply_fighter(fighter2_panel, config["fighter2"])
	if config.has("match"):
		_apply_match(config["match"])

func _apply_fighter(panel: VBoxContainer, fighter: Dictionary) -> void:
	panel.get_node("NameField").text = fighter.get("name", "")
	panel.get_node("AgeField").value = fighter.get("age", 25)
	panel.get_node("HeightField").value = fighter.get("height_cm", 175)
	_select_text(panel.get_node("WeightClassField"), fighter.get("weight_class", ""))
	_select_text(panel.get_node("BodyArchetypeField"), fighter.get("body_archetype", ""))
	_select_text(panel.get_node("BeltField"), fighter.get("belt_rank", ""))
	_select_text(panel.get_node("DominantSideField"), fighter.get("dominant_side", ""))
	var p: Dictionary = fighter.get("personality_facets", {})
	panel.get_node("AggressivePatientSlider").value = p.get("aggressive_patient", 5)
	panel.get_node("TechnicalAthleticSlider").value = p.get("technical_athletic", 5)
	panel.get_node("ConfidentAnxiousSlider").value = p.get("confident_anxious", 5)
	panel.get_node("LoyalImprovSlider").value = p.get("loyal_improv", 5)
	var c: Dictionary = fighter.get("capability", {})
	panel.get_node("HandsLeftSlider").value = c.get("hands_left", 5)
	panel.get_node("HandsRightSlider").value = c.get("hands_right", 5)
	panel.get_node("ForearmsLeftSlider").value = c.get("forearms_left", 5)
	panel.get_node("ForearmsRightSlider").value = c.get("forearms_right", 5)
	panel.get_node("LegsLeftSlider").value = c.get("legs_left", 5)
	panel.get_node("LegsRightSlider").value = c.get("legs_right", 5)
	panel.get_node("CoreSlider").value = c.get("core", 5)
	panel.get_node("LowerBackSlider").value = c.get("lower_back", 5)
	panel.get_node("NeckSlider").value = c.get("neck", 5)
	panel.get_node("CardioCapacitySlider").value = c.get("cardio_capacity", 5)
	panel.get_node("CardioEfficiencySlider").value = c.get("cardio_efficiency", 5)
	panel.get_node("FightIQSlider").value = c.get("fight_iq", 5)
	panel.get_node("ComposureCeilingSlider").value = c.get("composure_ceiling", 5)
	panel.get_node("NeWazaSkillSlider").value = c.get("ne_waza_skill", 5)
	panel.get_node("OtherBodyPartsGlobalSlider").value = c.get("other_body_parts_global", 5)

func _apply_match(m: Dictionary) -> void:
	_select_text(match_panel.get_node("StartingPositionField"), m.get("starting_position", ""))
	match_panel.get_node("TimeOnClockField").value = m.get("time_on_clock", 240)
	_select_text(match_panel.get_node("ForcedThrowField"), m.get("forced_throw", "NONE"))
	_select_text(match_panel.get_node("RefPersonalityField"), m.get("ref_personality", "NEUTRAL"))

func _select_text(option_button: OptionButton, target: String) -> void:
	for i in range(option_button.item_count):
		if option_button.get_item_text(i) == target:
			option_button.select(i)
			return

# ============================================================
# Presets (Phase 6 will fill these in)
# ============================================================
func _on_preset_selector_item_selected(index: int) -> void:
	var preset_name := preset_selector.get_item_text(index)
	if preset_name == "(none)":
		return
	log_output.text = "Preset '%s' is a Phase 6 stub — not implemented yet." % preset_name
