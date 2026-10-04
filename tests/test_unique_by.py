"""Tests for the ``unique_by`` contract for ``many`` loading."""

import pytest

from marshmallow import Schema, fields, post_load
from marshmallow.exceptions import ValidationError


class ItemSchema(Schema):
    class Meta:
        unique_by = ("id",)

    id = fields.Int()
    name = fields.Str()


def test_unique_by_detects_duplicate_after_conversion():
    # "1" and 1 both convert to the integer 1, so they are duplicates.
    data = [{"id": "1", "name": "a"}, {"id": 2, "name": "b"}, {"id": 1, "name": "c"}]
    with pytest.raises(ValidationError) as excinfo:
        ItemSchema().load(data, many=True)  # type: ignore[arg-type]
    errors = excinfo.value.messages
    # Both duplicate items are reported with their original indices.
    assert 0 in errors
    assert 2 in errors
    assert "id" in errors[0]
    assert "id" in errors[2]
    # The schema-level message lists every index sharing the identity.
    assert errors["_schema"] == [
        "Duplicate identity for unique_by fields ('id',) at indices [0, 2]."
    ]


def test_unique_by_no_duplicate():
    data = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    result = ItemSchema().load(data, many=True)
    assert result == [
        {"id": 1, "name": "a"},
        {"id": 2, "name": "b"},
    ]


def test_unique_by_single_string():
    class SingleSchema(Schema):
        class Meta:
            unique_by = "id"

        id = fields.Int()

    data = [{"id": 1}, {"id": 1}]
    with pytest.raises(ValidationError) as excinfo:
        SingleSchema().load(data, many=True)
    assert set(excinfo.value.messages) == {"_schema", 0, 1}


def test_unique_by_composite_key():
    # Different tenant -> not a duplicate even though id matches.
    class TenantItemSchema(Schema):
        class Meta:
            unique_by = ("tenant", "id")

        id = fields.Int()
        tenant = fields.Str()

    data = [{"tenant": "a", "id": 1}, {"tenant": "b", "id": 1}]
    result = TenantItemSchema().load(data, many=True)
    assert len(result) == 2

    # Same tenant + id -> duplicate.
    data = [{"tenant": "a", "id": 1}, {"tenant": "a", "id": 1}]
    with pytest.raises(ValidationError) as excinfo:
        TenantItemSchema().load(data, many=True)
    assert set(excinfo.value.messages) == {"_schema", 0, 1}


def test_unique_by_reports_all_related_indices():
    data = [{"id": 1}, {"id": 2}, {"id": 1}, {"id": 3}, {"id": 1}]
    with pytest.raises(ValidationError) as excinfo:
        ItemSchema().load(data, many=True)
    errors = excinfo.value.messages
    assert errors["_schema"] == [
        "Duplicate identity for unique_by fields ('id',) at indices [0, 2, 4]."
    ]
    for idx in (0, 2, 4):
        assert idx in errors


def test_unique_by_indices_not_shifted_by_invalid_records():
    # Index 1 fails conversion; the duplicate indices 0 and 2 must keep their
    # original positions rather than being renumbered after filtering.
    data = [{"id": "1"}, {"id": "not-an-int"}, {"id": 1}]
    with pytest.raises(ValidationError) as excinfo:
        ItemSchema().load(data, many=True)  # type: ignore[arg-type]
    errors = excinfo.value.messages
    assert set(errors) == {"_schema", 0, 1, 2}
    assert "Not a valid integer." in errors[1]["id"]
    assert "Duplicate identity." in errors[0]["id"]
    assert "Duplicate identity." in errors[2]["id"]
    assert errors["_schema"] == [
        "Duplicate identity for unique_by fields ('id',) at indices [0, 2]."
    ]


def test_unique_by_missing_identity_not_grouped():
    # Two records missing the identity field must not be grouped together.
    data = [{"name": "a"}, {"name": "b"}, {"id": 1}]
    result = ItemSchema().load(data, many=True)  # type: ignore[arg-type]
    assert len(result) == 3


def test_unique_by_null_identity_not_grouped():
    # Two records with null identity must not be grouped together.
    data = [{"id": None}, {"id": None}, {"id": 1}]
    with pytest.raises(ValidationError) as excinfo:
        ItemSchema().load(data, many=True)  # type: ignore[arg-type]
    errors = excinfo.value.messages
    # Only the null field errors; no duplicate identity error.
    assert "_schema" not in errors
    assert "Field may not be null." in errors[0]["id"]
    assert "Field may not be null." in errors[1]["id"]


def test_unique_by_conversion_failure_not_grouped():
    # Two records whose identity failed conversion must not be grouped.
    data = [{"id": "bad"}, {"id": "worse"}, {"id": 1}]
    with pytest.raises(ValidationError) as excinfo:
        ItemSchema().load(data, many=True)  # type: ignore[arg-type]
    errors = excinfo.value.messages
    assert "_schema" not in errors
    assert "Not a valid integer." in errors[0]["id"]
    assert "Not a valid integer." in errors[1]["id"]


def test_unique_by_field_errors_and_duplicates_aggregated():
    # A field error on a non-identity field coexists with the duplicate error.
    class NameSchema(Schema):
        class Meta:
            unique_by = ("id",)

        id = fields.Int()
        name = fields.Str(required=True)

    data = [{"id": 1, "name": "a"}, {"id": 1}]
    with pytest.raises(ValidationError) as excinfo:
        NameSchema().load(data, many=True)  # type: ignore[arg-type]
    errors = excinfo.value.messages
    assert "Duplicate identity." in errors[0]["id"]
    assert "Duplicate identity." in errors[1]["id"]
    assert "Missing data for required field." in errors[1]["name"]
    assert "_schema" in errors


def test_unique_by_prevents_post_load_construction():
    constructed = []

    class ConstructSchema(Schema):
        class Meta:
            unique_by = ("id",)

        id = fields.Int()

        @post_load
        def make(self, data, **kwargs):
            constructed.append(data)
            return data

    data = [{"id": 1}, {"id": 1}]
    with pytest.raises(ValidationError):
        ConstructSchema().load(data, many=True)
    assert constructed == []


def test_unique_by_disabled_by_default():
    class PlainSchema(Schema):
        id = fields.Int()

    data = [{"id": 1}, {"id": 1}]
    # No unique_by -> original behavior, no error.
    result = PlainSchema().load(data, many=True)
    assert result == [{"id": 1}, {"id": 1}]


def test_unique_by_not_checked_for_single_object():
    data = {"id": 1}
    result = ItemSchema().load(data, many=False)
    assert result == {"id": 1}


def test_unique_by_with_data_key():
    class DataKeySchema(Schema):
        class Meta:
            unique_by = ("id",)

        id = fields.Int(data_key="ID")

    data = [{"ID": "1"}, {"ID": 1}]
    with pytest.raises(ValidationError) as excinfo:
        DataKeySchema().load(data, many=True)  # type: ignore[arg-type]
    errors = excinfo.value.messages
    assert "ID" in errors[0]
    assert "ID" in errors[1]
    assert errors["_schema"] == [
        "Duplicate identity for unique_by fields ('id',) at indices [0, 1]."
    ]


def test_unique_by_invalid_field_raises():
    class BadSchema(Schema):
        class Meta:
            unique_by = ("nope",)

        id = fields.Int()

    with pytest.raises(ValueError):
        BadSchema()


def test_unique_by_invalid_option_type_raises():
    with pytest.raises(ValueError):

        class BadSchema(Schema):
            class Meta:
                unique_by = 123

            id = fields.Int()


def test_unique_by_per_load_override():
    class PlainSchema(Schema):
        id = fields.Int()

    data = [{"id": 1}, {"id": 1}]
    with pytest.raises(ValidationError) as excinfo:
        PlainSchema().load(data, many=True, unique_by=("id",))
    assert set(excinfo.value.messages) == {"_schema", 0, 1}


def test_unique_by_validate_reports_duplicates():
    data = [{"id": 1}, {"id": 1}]
    errors = ItemSchema().validate(data, many=True)
    assert set(errors) == {"_schema", 0, 1}


def test_unique_by_nested_many():
    class ChildSchema(Schema):
        class Meta:
            unique_by = ("id",)

        id = fields.Int()

    class ParentSchema(Schema):
        name = fields.Str()
        children = fields.Nested(ChildSchema, many=True)

    data = {"name": "p", "children": [{"id": 1}, {"id": "1"}]}
    with pytest.raises(ValidationError) as excinfo:
        ParentSchema().load(data)
    errors = excinfo.value.messages
    assert "children" in errors
    assert set(errors["children"]) == {"_schema", 0, 1}
    assert errors["children"]["_schema"] == [
        "Duplicate identity for unique_by fields ('id',) at indices [0, 1]."
    ]


def test_unique_by_nested_many_no_duplicate():
    class ChildSchema(Schema):
        class Meta:
            unique_by = ("id",)

        id = fields.Int()

    class ParentSchema(Schema):
        name = fields.Str()
        children = fields.Nested(ChildSchema, many=True)

    data = {"name": "p", "children": [{"id": 1}, {"id": 2}]}
    result = ParentSchema().load(data)
    assert result == {"name": "p", "children": [{"id": 1}, {"id": 2}]}


def test_unique_by_nested_many_missing_identity():
    class ChildSchema(Schema):
        class Meta:
            unique_by = ("id",)

        id = fields.Int()
        name = fields.Str()

    class ParentSchema(Schema):
        children = fields.Nested(ChildSchema, many=True)

    # Two records missing the identity field are not grouped.
    data = {"children": [{"name": "a"}, {"name": "b"}, {"id": 1}]}
    result = ParentSchema().load(data)
    assert len(result["children"]) == 3


def test_unique_by_error_structure_example():
    """Document the exact error structure for a duplicate identity."""
    data = [{"id": "1"}, {"id": 1}]
    with pytest.raises(ValidationError) as excinfo:
        ItemSchema().load(data, many=True)  # type: ignore[arg-type]
    assert excinfo.value.messages == {
        "_schema": [
            "Duplicate identity for unique_by fields ('id',) at indices [0, 1]."
        ],
        0: {"id": ["Duplicate identity."]},
        1: {"id": ["Duplicate identity."]},
    }
