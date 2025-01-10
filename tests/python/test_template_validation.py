import pytest
from scheduler import logic
from scheduler import model

def test_template_validation():
    device = model.Device(id="test_scanner", label="Test Scanner")
    
    # Test empty templates
    errors = logic.validate_templates_before_application(device, "")
    assert "no templates to apply" in errors
    
    # Test invalid template
    errors = logic.validate_templates_before_application(device, "invalid_template")
    assert "invalid template codes provided" in errors

def test_verify_template_diffs():
    institutes = [("inst1", "Institute 1")]
    groups = [("group1", "Group 1")]
    members = {"group1": [("user1", "User 1")]}
    
    diffs = [{"id": 1, "inst": ["old", "new"]}]
    entries = [model.TemplateEntry(id=1)]
    
    errors, staged = logic.verify_and_prep_template_diffs(
        diffs, entries, institutes, groups, members
    )
    assert len(errors) > 0 