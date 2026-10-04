"""Tests for the Schema ``unique_by`` contract on ``many`` loads.

Contract registration example::

    class LineItemSchema(Schema):
        tenant = fields.Str()
        id = fields.Int(data_key="lineId")

        class Meta:
            unique_by = ("tenant", "id")

Error structure example (duplicate group at original input indices 0 and 2)::

    {
        0: {
            "_schema": [
                "Duplicate record for unique field(s) "
                "('tenant', 'lineId'): identical values at "
                "indices [0, 2]."
            ]
        },
        2: {
            "_schema": [
                "Duplicate record for unique field(s) "
                "('tenant', 'lineId'): identical values at "
                "indices [0, 2]."
            ]
        },
    }

Run locally with::

    python -m pytest tests/test_unique_by.py -v
"""

import datetime as dt

import pytest

from marshmallow import Schema, ValidationError, fields, post_load


class ItemSchema(Schema):
    id = fields.Int()

    class Meta:
        unique_by = "id"


class LineItemSchema(Schema):
    tenant = fields.Str()
    id = fields.Int(data_key="lineId")

    class Meta:
        unique_by = ("tenant", "id")


class TestContractRegistration:
    def test_meta_registration_normalizes_to_tuple(self):
        assert ItemSchema().unique_by == ("id",)
        assert LineItemSchema().unique_by == ("tenant", "id")

    def test_constructor_param_registers_contract(self):
        class PlainSchema(Schema):
            id = fields.Int()

        schema = PlainSchema(unique_by="id")
        with pytest.raises(ValidationError):
            schema.load([{"id": 1}, {"id": 1}], many=True)

    def test_constructor_param_disables_meta_contract(self):
        schema = ItemSchema(unique_by=())
        loaded = schema.load([{"id": 1}, {"id": 1}], many=True)
        assert loaded == [{"id": 1}, {"id": 1}]

    def test_unknown_unique_by_field_raises(self):
        class BadSchema(Schema):
            id = fields.Int()

            class Meta:
                unique_by = ("nope",)

        with pytest.raises(ValueError, match="nope"):
            BadSchema()

    def test_unique_by_may_reference_data_key(self):
        class DataKeySchema(Schema):
            id = fields.Int(data_key="itemId")

            class Meta:
                unique_by = ("itemId",)

        with pytest.raises(ValidationError):
            DataKeySchema().load([{"itemId": 1}, {"itemId": 1}], many=True)


class TestDuplicateDetection:
    def test_identity_uses_converted_values(self):
        # "1" and 1 both convert to int 1 -> duplicate at both indices
        with pytest.raises(ValidationError) as excinfo:
            ItemSchema().load([{"id": "1"}, {"id": 1}], many=True)
        errors = excinfo.value.messages
        assert set(errors) == {0, 1}
        for idx in (0, 1):
            (message,) = errors[idx]["_schema"]
            assert "('id',)" in message
            assert "indices [0, 1]" in message

    def test_error_structure_reports_all_original_indices(self):
        with pytest.raises(ValidationError) as excinfo:
            ItemSchema().load([{"id": "1"}, {"id": 2}, {"id": 1}], many=True)
        errors = excinfo.value.messages
        assert set(errors) == {0, 2}
        assert "indices [0, 2]" in errors[0]["_schema"][0]
        assert errors[0] == errors[2]

    def test_composite_identity_with_distinct_tenant_is_not_duplicate(self):
        result = LineItemSchema().load(
            [
                {"tenant": "a", "lineId": 1},
                {"tenant": "b", "lineId": "1"},
            ],
            many=True,
        )
        assert result == [
            {"tenant": "a", "id": 1},
            {"tenant": "b", "id": 1},
        ]

    def test_composite_identity_with_same_tenant_is_duplicate(self):
        with pytest.raises(ValidationError) as excinfo:
            LineItemSchema().load(
                [
                    {"tenant": "a", "lineId": 1},
                    {"tenant": "a", "lineId": "1"},
                ],
                many=True,
            )
        errors = excinfo.value.messages
        assert set(errors) == {0, 1}
        # field paths in the message follow the data_key mapping
        assert "('tenant', 'lineId')" in errors[0]["_schema"][0]

    def test_identity_uses_converted_date_values(self):
        class EventSchema(Schema):
            day = fields.Date()

            class Meta:
                unique_by = "day"

        with pytest.raises(ValidationError) as excinfo:
            EventSchema().load(
                [{"day": "2020-01-01"}, {"day": dt.date(2020, 1, 1)}],
                many=True,
            )
        assert set(excinfo.value.messages) == {0, 1}

    def test_validate_reports_duplicates(self):
        errors = ItemSchema().validate([{"id": 1}, {"id": 1}], many=True)
        assert set(errors) == {0, 1}

    def test_single_object_load_is_unaffected(self):
        assert ItemSchema().load({"id": 1}) == {"id": 1}

    def test_no_unique_by_keeps_original_behavior(self):
        class PlainSchema(Schema):
            id = fields.Int()

        loaded = PlainSchema().load([{"id": 1}, {"id": 1}], many=True)
        assert loaded == [{"id": 1}, {"id": 1}]


class TestPostLoadGating:
    def test_post_load_not_called_on_any_duplicate(self):
        constructed = []

        class ObjSchema(Schema):
            id = fields.Int()

            class Meta:
                unique_by = "id"

            @post_load
            def make_object(self, data, **kwargs):
                constructed.append(data)
                return data

        with pytest.raises(ValidationError):
            ObjSchema().load([{"id": "1"}, {"id": 2}, {"id": 1}], many=True)
        assert constructed == []

    def test_post_load_called_when_unique(self):
        constructed = []

        class ObjSchema(Schema):
            id = fields.Int()

            class Meta:
                unique_by = "id"

            @post_load
            def make_object(self, data, **kwargs):
                constructed.append(data)
                return data

        loaded = ObjSchema().load([{"id": 1}, {"id": 2}], many=True)
        assert loaded == [{"id": 1}, {"id": 2}]
        assert constructed == [{"id": 1}, {"id": 2}]


class TestUnidentifiableRecords:
    def test_missing_identity_is_not_silently_merged(self):
        class NameSchema(Schema):
            id = fields.Int()
            name = fields.Str()

            class Meta:
                unique_by = "id"

        with pytest.raises(ValidationError) as excinfo:
            NameSchema().load([{"name": "a"}, {"name": "b"}], many=True)
        errors = excinfo.value.messages
        # each record is reported at its own index, not grouped as duplicates
        assert set(errors) == {0, 1}
        for idx in (0, 1):
            assert "_schema" not in errors[idx]
            (message,) = errors[idx]["id"]
            assert "Cannot determine unique identity" in message
            assert "'id'" in message

    def test_null_identity_is_not_silently_merged(self):
        class NullableSchema(Schema):
            id = fields.Int(allow_none=True)

            class Meta:
                unique_by = "id"

        with pytest.raises(ValidationError) as excinfo:
            NullableSchema().load([{"id": None}, {"id": None}], many=True)
        errors = excinfo.value.messages
        assert set(errors) == {0, 1}
        for idx in (0, 1):
            assert "_schema" not in errors[idx]
            assert "Cannot determine unique identity" in errors[idx]["id"][0]

    def test_conversion_failure_does_not_collapse_identity(self):
        # "x" fails int conversion; it must not merge with missing records
        class NameSchema(Schema):
            id = fields.Int()
            name = fields.Str()

            class Meta:
                unique_by = "id"

        with pytest.raises(ValidationError) as excinfo:
            NameSchema().load([{"id": "x"}, {"name": "b"}], many=True)
        errors = excinfo.value.messages
        assert set(errors) == {0, 1}
        assert "Not a valid integer." in errors[0]["id"]
        assert "_schema" not in errors[0]
        assert "_schema" not in errors[1]


class TestIndexStabilityAndAggregation:
    def test_error_index_not_shifted_by_invalid_records(self):
        with pytest.raises(ValidationError) as excinfo:
            ItemSchema().load([{"id": 1}, {"id": "not-an-int"}, {"id": "1"}], many=True)
        errors = excinfo.value.messages
        # field error stays at its original index 1...
        assert set(errors) == {0, 1, 2}
        assert errors[1] == {"id": ["Not a valid integer."]}
        # ...and the duplicate group reports original indices 0 and 2
        assert "indices [0, 2]" in errors[0]["_schema"][0]
        assert "indices [0, 2]" in errors[2]["_schema"][0]

    def test_field_errors_and_duplicates_are_aggregated(self):
        class UserSchema(Schema):
            id = fields.Int()
            email = fields.Email()

            class Meta:
                unique_by = "id"

        with pytest.raises(ValidationError) as excinfo:
            UserSchema().load(
                [
                    {"id": 1, "email": "a@example.com"},
                    {"id": 2, "email": "not-an-email"},
                    {"id": "1", "email": "b@example.com"},
                ],
                many=True,
            )
        errors = excinfo.value.messages
        assert set(errors) == {0, 1, 2}
        assert errors[1] == {"email": ["Not a valid email address."]}
        assert "indices [0, 2]" in errors[0]["_schema"][0]
        assert "indices [0, 2]" in errors[2]["_schema"][0]


class TestNestedMany:
    @pytest.fixture
    def order_schema(self):
        class LineSchema(Schema):
            sku = fields.Str()

            class Meta:
                unique_by = "sku"

        class OrderSchema(Schema):
            id = fields.Int()
            lines = fields.Nested(LineSchema, many=True)

        return OrderSchema()

    def test_nested_many_checks_its_own_collection(self, order_schema):
        with pytest.raises(ValidationError) as excinfo:
            order_schema.load(
                {"id": 1, "lines": [{"sku": "a"}, {"sku": "b"}, {"sku": "a"}]}
            )
        errors = excinfo.value.messages
        assert set(errors["lines"]) == {0, 2}
        assert "indices [0, 2]" in errors["lines"][0]["_schema"][0]

    def test_nested_many_distinct_collections_are_independent(self):
        class LineSchema(Schema):
            sku = fields.Str()

            class Meta:
                unique_by = "sku"

        class OrderSchema(Schema):
            lines = fields.Nested(LineSchema, many=True)

        # same sku in different orders is fine: each nested collection is
        # checked independently
        result = OrderSchema().load(
            [{"lines": [{"sku": "a"}]}, {"lines": [{"sku": "a"}]}],
            many=True,
        )
        assert result == [{"lines": [{"sku": "a"}]}, {"lines": [{"sku": "a"}]}]

    def test_nested_many_valid_collection_loads(self, order_schema):
        result = order_schema.load({"id": 1, "lines": [{"sku": "a"}, {"sku": "b"}]})
        assert result == {"id": 1, "lines": [{"sku": "a"}, {"sku": "b"}]}
