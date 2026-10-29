from scheduler.load_test_support import (
    Assignment,
    classify_scheduler_save,
    extract_csrf_token,
    extract_datalist_options,
    extract_first_assignment,
    jump_day,
    synthetic_slot_id,
)


def test_extract_csrf_token_returns_hidden_input_value():
    html = '<form><input id="csrf_token" name="csrf_token" value="abc123" /></form>'

    assert extract_csrf_token(html) == "abc123"


def test_extract_datalist_options_and_first_assignment():
    html = """
    <datalist id="groups">
      <option value="BEI">Brain</option>
      <option value="EEG">EEG</option>
    </datalist>
    <datalist id="members-of-BEI">
      <option value="user0048">Reza</option>
    </datalist>
    <datalist id="members-of-EEG">
      <option value="person0073">person0073</option>
    </datalist>
    """

    assert extract_datalist_options(html) == {
        "groups": ["BEI", "EEG"],
        "members-of-BEI": ["user0048"],
        "members-of-EEG": ["person0073"],
    }
    assert extract_first_assignment(html) == Assignment(group="BEI", member="user0048")


def test_extract_first_assignment_returns_none_when_groups_have_no_members():
    html = """
    <datalist id="groups">
      <option value="BEI">Brain</option>
    </datalist>
    <datalist id="members-of-BEI"></datalist>
    """

    assert extract_first_assignment(html) is None


def test_jump_day_and_synthetic_slot_id_are_deterministic():
    assert jump_day("2035-04-10", 3) == "2035-04-13"
    assert synthetic_slot_id("2035-04-13", 8) == "new-2035-04-13-08"


def test_classify_scheduler_save_distinguishes_saved_conflict_and_error():
    assert classify_scheduler_save({"saved": 1}, "new-2035-04-13-08") == "saved"
    assert (
        classify_scheduler_save(
            {
                "errors": {
                    "new-2035-04-13-08": [
                        {"code": "slot_conflict"},
                        {"type": "overwrote"},
                    ]
                }
            },
            "new-2035-04-13-08",
        )
        == "conflict"
    )
    assert (
        classify_scheduler_save(
            {"errors": {"new-2035-04-13-08": [{"code": "invalid_group"}]}},
            "new-2035-04-13-08",
        )
        == "error"
    )
    assert classify_scheduler_save({}, "new-2035-04-13-08") == "noop"
