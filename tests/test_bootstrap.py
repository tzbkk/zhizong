import importlib.resources

import jsonschema
import yaml


def test_bootstrap_self_validation():
    with (importlib.resources.files("zhizong") / "versions" / "1.yaml").open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    validator = jsonschema.Draft202012Validator(doc["Definition"]["Shapes"]["Document"])
    errors = list(validator.iter_errors(doc))
    assert len(errors) == 0, f"Bootstrap validation failed with {len(errors)} errors"


def test_bootstrap_invariants_count():
    with (importlib.resources.files("zhizong") / "versions" / "1.yaml").open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    invariants = doc["Definition"]["Invariants"]
    assert len(invariants) == 21, f"Expected 21 invariants, got {len(invariants)}"

    expected_ids = {f"R{i:02d}" for i in range(1, 22)}
    actual_ids = {inv["Id"] for inv in invariants}
    assert actual_ids == expected_ids, f"Expected IDs {expected_ids}, got {actual_ids}"