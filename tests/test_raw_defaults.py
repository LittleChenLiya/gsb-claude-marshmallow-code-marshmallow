"""Tests for the explicit ``raw_defaults`` mode.

In ``raw_defaults`` mode, ``load_default`` values produced for missing fields
are deserialized and validated like ordinary raw input instead of bypassing
validation. The mode is opt-in via ``Schema.Meta.raw_defaults``,
``Schema(raw_defaults=...)``, or ``Schema.load(..., raw_defaults=True)`` and is
inherited by ``Nested`` fields and ``many=True`` collections.

Run the targeted tests for this feature with::

    python -m pytest tests/test_raw_defaults.py -v
"""

import pytest

from marshmallow import (
    Schema,
    ValidationError,
    fields,
    missing,
    validate,
    validates_schema,
)


class TwoFieldSchema(Schema):
    """Two-field example schema used across the raw_defaults tests."""

    count = fields.Integer(load_default="12")
    ratio = fields.Float(load_default="0.5")


class TestRawDefaultsConversion:
    def test_integer_string_default_is_converted(self):
        # Integer default "12" is converted to 12 like ordinary raw input
        assert TwoFieldSchema().load({}, raw_defaults=True) == {
            "count": 12,
            "ratio": 0.5,
        }

    def test_default_mode_unchanged(self):
        # Without raw_defaults, typed defaults are used as-is (no conversion)
        assert TwoFieldSchema().load({}) == {"count": "12", "ratio": "0.5"}

    def test_meta_option_enables_mode(self):
        class MetaSchema(TwoFieldSchema):
            class Meta:
                raw_defaults = True

        assert MetaSchema().load({}) == {"count": 12, "ratio": 0.5}

    def test_init_kwarg_enables_mode(self):
        assert TwoFieldSchema(raw_defaults=True).load({}) == {
            "count": 12,
            "ratio": 0.5,
        }

    def test_load_kwarg_overrides_meta(self):
        class MetaSchema(TwoFieldSchema):
            class Meta:
                raw_defaults = True

        assert MetaSchema().load({}, raw_defaults=False) == {
            "count": "12",
            "ratio": "0.5",
        }

    def test_provided_values_still_deserialized_normally(self):
        assert TwoFieldSchema().load(
            {"count": "3", "ratio": "1.5"}, raw_defaults=True
        ) == {"count": 3, "ratio": 1.5}


class TestRawDefaultsValidation:
    def test_invalid_default_reports_default_source(self):
        class MinSchema(Schema):
            count = fields.Integer(load_default="0", validate=validate.Range(min=1))

        with pytest.raises(ValidationError) as excinfo:
            MinSchema().load({}, raw_defaults=True)
        assert excinfo.value.messages == {
            "count": ["Default value: Must be greater than or equal to 1."]
        }

    def test_undeserializable_default_reports_default_source(self):
        class BadSchema(Schema):
            count = fields.Integer(load_default="not-a-number")

        with pytest.raises(ValidationError) as excinfo:
            BadSchema().load({}, raw_defaults=True)
        assert excinfo.value.messages == {
            "count": ["Default value: Not a valid integer."]
        }

    def test_none_default_respects_allow_none(self):
        class NoneAllowed(Schema):
            value = fields.Integer(load_default=None)

        class NoneForbidden(Schema):
            value = fields.Integer(load_default=lambda: None, allow_none=False)

        # load_default=None implies allow_none, so None passes through
        assert NoneAllowed().load({}, raw_defaults=True) == {"value": None}
        # A None produced by a default factory is validated like raw input
        with pytest.raises(ValidationError) as excinfo:
            NoneForbidden().load({}, raw_defaults=True)
        assert excinfo.value.messages == {
            "value": ["Default value: Field may not be null."]
        }

    def test_missing_default_omits_field(self):
        class MissingDefault(Schema):
            value = fields.Integer(load_default=lambda: missing)

        assert MissingDefault().load({}, raw_defaults=True) == {}

    def test_field_without_default_behaves_as_before(self):
        class NoDefault(Schema):
            value = fields.Integer()

        assert NoDefault().load({}, raw_defaults=True) == {}

        class Required(Schema):
            value = fields.Integer(required=True)

        with pytest.raises(ValidationError) as excinfo:
            Required().load({}, raw_defaults=True)
        assert excinfo.value.messages == {"value": ["Missing data for required field."]}


class TestRawDefaultsFactory:
    def test_factory_called_at_most_once_per_load(self):
        calls = []

        def factory():
            calls.append(1)
            return "12"

        class FactorySchema(Schema):
            count = fields.Integer(load_default=factory)

        assert FactorySchema().load({}, raw_defaults=True) == {"count": 12}
        assert len(calls) == 1

    def test_partial_skipped_field_does_not_call_factory(self):
        calls = []

        def factory():
            calls.append(1)
            return "12"

        class FactorySchema(Schema):
            count = fields.Integer(load_default=factory)

        # partial skips the missing field entirely: the factory is never called
        assert FactorySchema().load({}, partial=True, raw_defaults=True) == {}
        assert len(calls) == 0

        assert FactorySchema().load({}, partial=["count"], raw_defaults=True) == {}
        assert len(calls) == 0


class TestRawDefaultsInheritance:
    def test_nested_inherits_mode(self):
        class Inner(Schema):
            value = fields.Integer(load_default="7")

        class Outer(Schema):
            inner = fields.Nested(Inner)

        assert Outer().load({"inner": {}}, raw_defaults=True) == {"inner": {"value": 7}}
        # Nested schema defaults are untouched when the mode is off
        assert Outer().load({"inner": {}}) == {"inner": {"value": "7"}}

    def test_nested_default_dict_is_deserialized(self):
        class Inner(Schema):
            value = fields.Integer(load_default="7")

        class Outer(Schema):
            inner = fields.Nested(Inner, load_default=dict)

        assert Outer().load({}, raw_defaults=True) == {"inner": {"value": 7}}

    def test_many_inherits_mode(self):
        class ManySchema(Schema):
            count = fields.Integer(load_default="12")

        schema = ManySchema(many=True)
        assert schema.load([{}, {}], raw_defaults=True) == [
            {"count": 12},
            {"count": 12},
        ]

    def test_list_of_nested_inherits_mode(self):
        class Inner(Schema):
            value = fields.Integer(load_default="7")

        class Outer(Schema):
            inners = fields.List(fields.Nested(Inner))

        assert Outer().load({"inners": [{}, {}]}, raw_defaults=True) == {
            "inners": [{"value": 7}, {"value": 7}]
        }


class TestRawDefaultsSchemaLevelValidation:
    def test_schema_level_validator_sees_converted_values(self):
        seen = {}

        class CheckedSchema(Schema):
            count = fields.Integer(load_default="12")
            ratio = fields.Float(load_default="0.5")

            @validates_schema
            def check_types(self, data, **kwargs):
                seen.update(data)
                if data["count"] < 1:
                    raise ValidationError("count must be positive")

        assert CheckedSchema().load({}, raw_defaults=True) == {
            "count": 12,
            "ratio": 0.5,
        }
        # The schema-level validator received the converted values
        assert seen == {"count": 12, "ratio": 0.5}

    def test_validate_method_supports_raw_defaults(self):
        class MinSchema(Schema):
            count = fields.Integer(load_default="0", validate=validate.Range(min=1))

        assert MinSchema().validate({}, raw_defaults=True) == {
            "count": ["Default value: Must be greater than or equal to 1."]
        }
        assert MinSchema().validate({}) == {}
