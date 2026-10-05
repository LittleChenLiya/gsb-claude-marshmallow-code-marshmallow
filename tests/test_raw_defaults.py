"""Tests for the ``raw_defaults`` mode."""

import pytest

from marshmallow import Schema, fields, validate, validates_schema
from marshmallow.exceptions import ValidationError


class TestRawDefaultsConversion:
    def test_string_default_converts_to_integer(self):
        class MySchema(Schema):
            class Meta:
                raw_defaults = True

            age = fields.Integer(load_default="12")

        assert MySchema().load({}) == {"age": 12}

    def test_two_field_example(self):
        class MySchema(Schema):
            class Meta:
                raw_defaults = True

            age = fields.Integer(load_default="12")
            name = fields.String(load_default="Monty")

        data = MySchema().load({})
        assert data == {"age": 12, "name": "Monty"}
        assert isinstance(data["age"], int)

    def test_default_validation_error_reports_default_source(self):
        class MySchema(Schema):
            class Meta:
                raw_defaults = True

            age = fields.Integer(load_default="0", validate=validate.Range(min=1))

        with pytest.raises(ValidationError) as exc:
            MySchema().load({})
        assert exc.value.source == "default"
        assert "default" in str(exc.value.messages).lower()

    def test_partial_skips_field_without_calling_factory(self):
        calls = []

        def factory():
            calls.append(1)
            return "5"

        class MySchema(Schema):
            class Meta:
                raw_defaults = True

            age = fields.Integer(load_default=factory)

        data = MySchema().load({}, partial=True)
        assert data == {}
        assert calls == []

    def test_factory_called_at_most_once_per_field(self):
        calls = []

        def factory():
            calls.append(1)
            return "9"

        class MySchema(Schema):
            class Meta:
                raw_defaults = True

            a = fields.Integer(load_default=factory)
            b = fields.Integer(load_default=factory)

        MySchema().load({})
        assert len(calls) == 2

    def test_schema_validator_sees_converted_value(self):
        seen = []

        class MySchema(Schema):
            class Meta:
                raw_defaults = True

            age = fields.Integer(load_default="12")

            @validates_schema
            def check_age(self, data, **kwargs):
                seen.append(data["age"])

        MySchema().load({})
        assert seen == [12]
        assert isinstance(seen[0], int)


class TestRawDefaultsMissingAndNull:
    def test_no_default_is_excluded(self):
        class MySchema(Schema):
            class Meta:
                raw_defaults = True

            name = fields.String()

        assert MySchema().load({}) == {}

    def test_factory_returning_missing_is_excluded(self):
        from marshmallow import missing

        class MySchema(Schema):
            class Meta:
                raw_defaults = True

            name = fields.String(load_default=lambda: missing)

        assert MySchema().load({}) == {}

    def test_null_default_with_allow_none(self):
        class MySchema(Schema):
            class Meta:
                raw_defaults = True

            name = fields.String(load_default=None)

        assert MySchema().load({}) == {"name": None}

    def test_null_default_without_allow_none_reports_default_source(self):
        class MySchema(Schema):
            class Meta:
                raw_defaults = True

            name = fields.String(load_default=None, allow_none=False)

        with pytest.raises(ValidationError) as exc:
            MySchema().load({})
        assert exc.value.source == "default"
        assert "default" in str(exc.value.messages).lower()


class TestRawDefaultsNestedAndMany:
    def test_nested_inherits_raw_defaults(self):
        class Child(Schema):
            class Meta:
                raw_defaults = True

            val = fields.Integer(load_default="7")

        class Parent(Schema):
            class Meta:
                raw_defaults = True

            child = fields.Nested(Child)

        assert Parent().load({"child": {}}) == {"child": {"val": 7}}

    def test_nested_missing_without_default_is_excluded(self):
        class Child(Schema):
            class Meta:
                raw_defaults = True

            val = fields.Integer(load_default="7")

        class Parent(Schema):
            class Meta:
                raw_defaults = True

            child = fields.Nested(Child)

        assert Parent().load({}) == {}

    def test_nested_with_load_default(self):
        class Child(Schema):
            class Meta:
                raw_defaults = True

            val = fields.Integer(load_default="7")

        class Parent(Schema):
            class Meta:
                raw_defaults = True

            child = fields.Nested(Child, load_default=dict)

        assert Parent().load({}) == {"child": {"val": 7}}

    def test_many_inherits_raw_defaults(self):
        class Item(Schema):
            class Meta:
                raw_defaults = True

            x = fields.Integer(load_default="3")

        assert Item(many=True).load([{}, {}]) == [{"x": 3}, {"x": 3}]

    def test_nested_many_inherits_raw_defaults(self):
        class Item(Schema):
            class Meta:
                raw_defaults = True

            x = fields.Integer(load_default="3")

        class Box(Schema):
            class Meta:
                raw_defaults = True

            items = fields.Nested(Item, many=True)

        assert Box().load({"items": [{}, {}]}) == {"items": [{"x": 3}, {"x": 3}]}

    def test_nested_raw_defaults_override(self):
        class Child(Schema):
            class Meta:
                raw_defaults = True

            val = fields.Integer(load_default="7")

        class Parent(Schema):
            class Meta:
                raw_defaults = True

            child = fields.Nested(Child, raw_defaults=False)

        assert Parent().load({"child": {}}) == {"child": {"val": "7"}}

    def test_pluck_inherits_raw_defaults(self):
        class Child(Schema):
            class Meta:
                raw_defaults = True

            val = fields.Integer(load_default="7")

        class Parent(Schema):
            class Meta:
                raw_defaults = True

            child = fields.Pluck(Child, "val")

        assert Parent().load({"child": "7"}) == {"child": {"val": 7}}


class TestRawDefaultsUnchanged:
    def test_typed_default_unchanged_when_disabled(self):
        class MySchema(Schema):
            age = fields.Integer(load_default=12)

        assert MySchema().load({}) == {"age": 12}

    def test_string_default_not_converted_when_disabled(self):
        class MySchema(Schema):
            age = fields.Integer(load_default="12")

        assert MySchema().load({}) == {"age": "12"}

    def test_default_bypasses_validation_when_disabled(self):
        class MySchema(Schema):
            age = fields.Integer(load_default="0", validate=validate.Range(min=1))

        assert MySchema().load({}) == {"age": "0"}

    def test_raw_defaults_can_be_enabled_per_load(self):
        class MySchema(Schema):
            age = fields.Integer(load_default="12")

        schema = MySchema()
        assert schema.load({}) == {"age": "12"}
        assert schema.load({}, raw_defaults=True) == {"age": 12}

    def test_raw_defaults_can_be_disabled_per_load(self):
        class MySchema(Schema):
            class Meta:
                raw_defaults = True

            age = fields.Integer(load_default="12")

        schema = MySchema()
        assert schema.load({}) == {"age": 12}
        assert schema.load({}, raw_defaults=False) == {"age": "12"}
