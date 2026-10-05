"""Tests for the explicit load permission context."""

from __future__ import annotations

import threading

import pytest

from marshmallow import Schema, fields
from marshmallow.exceptions import ValidationError


class CountingStr(fields.Str):
    """String field that counts how often its deserializer is invoked."""

    deserialize_count = 0

    def _deserialize(self, value, attr, data, **kwargs):
        type(self).deserialize_count += 1
        return super()._deserialize(value, attr, data, **kwargs)


@pytest.fixture(autouse=True)
def _reset_count():
    CountingStr.deserialize_count = 0
    yield
    CountingStr.deserialize_count = 0


class SecretSchema(Schema):
    name = fields.Str()
    secret = CountingStr(permissions="secret")


class TestFieldPermissions:
    def test_denied_without_permission(self):
        schema = SecretSchema()
        with pytest.raises(ValidationError) as exc_info:
            schema.load({"name": "monty", "secret": "shh"})
        assert "secret" in exc_info.value.messages
        assert CountingStr.deserialize_count == 0

    def test_granted_with_permission(self):
        schema = SecretSchema()
        result = schema.load(
            {"name": "monty", "secret": "shh"}, permissions=("secret",)
        )
        assert result == {"name": "monty", "secret": "shh"}
        assert CountingStr.deserialize_count == 1

    def test_permission_as_string(self):
        schema = SecretSchema()
        result = schema.load({"name": "monty", "secret": "shh"}, permissions="secret")
        assert result["secret"] == "shh"

    def test_missing_field_does_not_trigger_permission_error(self):
        schema = SecretSchema()
        result = schema.load({"name": "monty"})
        assert result == {"name": "monty"}
        assert CountingStr.deserialize_count == 0

    def test_load_default_does_not_trigger_permission_error(self):
        class SchemaWithDefault(Schema):
            secret = fields.Str(permissions="secret", load_default="default")

        assert SchemaWithDefault().load({}) == {"secret": "default"}

    def test_error_does_not_leak_input_value(self):
        schema = SecretSchema()
        with pytest.raises(ValidationError) as exc_info:
            schema.load({"name": "monty", "secret": "TOPSECRETVALUE"})
        messages = exc_info.value.messages
        assert "TOPSECRETVALUE" not in str(messages)

    def test_pre_load_not_called_without_permission(self):
        calls = []

        class SchemaWithPreLoad(Schema):
            secret = fields.Str(
                permissions="secret",
                pre_load=lambda value: calls.append(value) or value,
            )

        with pytest.raises(ValidationError):
            SchemaWithPreLoad().load({"secret": "shh"})
        assert calls == []

    def test_multiple_permissions_all_required(self):
        class MultiPermissionSchema(Schema):
            secret = fields.Str(permissions=("read", "write"))

        schema = MultiPermissionSchema()
        with pytest.raises(ValidationError):
            schema.load({"secret": "shh"}, permissions=("read",))
        assert schema.load({"secret": "shh"}, permissions=("read", "write")) == {
            "secret": "shh"
        }

    def test_field_state_not_mutated(self):
        field = fields.Str(permissions="secret")

        class StateSchema(Schema):
            secret = field

        schema = StateSchema()
        schema.load({"secret": "shh"}, permissions="secret")
        with pytest.raises(ValidationError):
            schema.load({"secret": "shh"})
        assert field.permissions == frozenset({"secret"})

    def test_dump_only_field_unaffected(self):
        class ReadOnlySchema(Schema):
            created = fields.DateTime(dump_only=True, permissions="secret")

        assert ReadOnlySchema().load({}) == {}

    def test_data_key_used_in_error(self):
        class DataKeySchema(Schema):
            secret = fields.Str(permissions="secret", data_key="secretKey")

        with pytest.raises(ValidationError) as exc_info:
            DataKeySchema().load({"secretKey": "shh"})
        assert "secretKey" in exc_info.value.messages


class TestNestedPermissions:
    def test_nested_field_itself_gated(self):
        class Inner(Schema):
            name = fields.Str()

        class Outer(Schema):
            inner = fields.Nested(Inner, permissions="admin")

        schema = Outer()
        with pytest.raises(ValidationError) as exc_info:
            schema.load({"inner": {"name": "monty"}})
        assert "inner" in exc_info.value.messages
        assert schema.load({"inner": {"name": "monty"}}, permissions="admin") == {
            "inner": {"name": "monty"}
        }

    def test_inner_field_permissions_propagate(self):
        class Inner(Schema):
            public = fields.Str()
            secret = CountingStr(permissions="secret")

        class Outer(Schema):
            inner = fields.Nested(Inner)

        schema = Outer()
        with pytest.raises(ValidationError) as exc_info:
            schema.load({"inner": {"public": "p", "secret": "shh"}})
        assert exc_info.value.messages == {
            "inner": {"secret": ["You do not have permission to load this field."]}
        }
        assert CountingStr.deserialize_count == 0
        assert schema.load(
            {"inner": {"public": "p", "secret": "shh"}}, permissions="secret"
        ) == {"inner": {"public": "p", "secret": "shh"}}
        assert CountingStr.deserialize_count == 1

    def test_nested_many_propagates(self):
        class Inner(Schema):
            secret = CountingStr(permissions="secret")

        class Outer(Schema):
            items = fields.List(fields.Nested(Inner))

        schema = Outer()
        with pytest.raises(ValidationError) as exc_info:
            schema.load({"items": [{"secret": "a"}, {"secret": "b"}]})
        assert exc_info.value.messages == {
            "items": {
                0: {"secret": ["You do not have permission to load this field."]},
                1: {"secret": ["You do not have permission to load this field."]},
            }
        }
        assert CountingStr.deserialize_count == 0
        assert schema.load(
            {"items": [{"secret": "a"}, {"secret": "b"}]}, permissions="secret"
        ) == {"items": [{"secret": "a"}, {"secret": "b"}]}
        assert CountingStr.deserialize_count == 2

    def test_schema_many_propagates(self):
        schema = SecretSchema(many=True)
        with pytest.raises(ValidationError) as exc_info:
            schema.load([{"secret": "a"}, {"secret": "b"}])
        assert set(exc_info.value.messages) == {0, 1}
        assert schema.load(
            [{"secret": "a"}, {"secret": "b"}], permissions="secret"
        ) == [{"secret": "a"}, {"secret": "b"}]

    def test_pluck_propagates(self):
        class Inner(Schema):
            name = fields.Str()

        class Outer(Schema):
            name = fields.Pluck(Inner, "name", permissions="admin")

        schema = Outer()
        with pytest.raises(ValidationError):
            schema.load({"name": "monty"})
        assert schema.load({"name": "monty"}, permissions="admin") == {
            "name": {"name": "monty"}
        }

    def test_tuple_propagates(self):
        class Inner(Schema):
            secret = fields.Str(permissions="secret")

        class Outer(Schema):
            pair = fields.Tuple((fields.Str(), fields.Nested(Inner)))

        schema = Outer()
        with pytest.raises(ValidationError) as exc_info:
            schema.load({"pair": ["x", {"secret": "shh"}]})
        assert exc_info.value.messages == {
            "pair": {1: {"secret": ["You do not have permission to load this field."]}}
        }
        assert schema.load(
            {"pair": ["x", {"secret": "shh"}]}, permissions="secret"
        ) == {"pair": ("x", {"secret": "shh"})}

    def test_dict_propagates(self):
        class Inner(Schema):
            secret = fields.Str(permissions="secret")

        class Outer(Schema):
            mapping = fields.Dict(keys=fields.Str(), values=fields.Nested(Inner))

        schema = Outer()
        with pytest.raises(ValidationError) as exc_info:
            schema.load({"mapping": {"k": {"secret": "shh"}}})
        assert exc_info.value.messages == {
            "mapping": {
                "k": {
                    "value": {
                        "secret": ["You do not have permission to load this field."]
                    }
                }
            }
        }
        assert schema.load(
            {"mapping": {"k": {"secret": "shh"}}}, permissions="secret"
        ) == {"mapping": {"k": {"secret": "shh"}}}


class TestPermissionContextIsolation:
    def test_consecutive_loads_do_not_leak_permissions(self):
        schema = SecretSchema()
        assert schema.load(
            {"name": "monty", "secret": "shh"}, permissions="secret"
        ) == {"name": "monty", "secret": "shh"}
        with pytest.raises(ValidationError):
            schema.load({"name": "monty", "secret": "shh"})
        # Granting again still works
        assert schema.load(
            {"name": "monty", "secret": "shh"}, permissions="secret"
        ) == {"name": "monty", "secret": "shh"}

    def test_concurrent_loads_do_not_leak_permissions(self):
        schema = SecretSchema()
        errors = []

        def worker(permissions, expect_success):
            for _ in range(100):
                try:
                    schema.load(
                        {"name": "monty", "secret": "shh"}, permissions=permissions
                    )
                    succeeded = True
                except ValidationError:
                    succeeded = False
                if succeeded != expect_success:
                    errors.append((permissions, expect_success, succeeded))

        granted = threading.Thread(target=worker, args=("secret", True))
        denied = threading.Thread(target=worker, args=(None, False))
        granted.start()
        denied.start()
        granted.join()
        denied.join()
        assert errors == []

    def test_validate_accepts_permissions(self):
        schema = SecretSchema()
        assert schema.validate({"name": "monty", "secret": "shh"}) == {
            "secret": ["You do not have permission to load this field."]
        }
        assert (
            schema.validate({"name": "monty", "secret": "shh"}, permissions="secret")
            == {}
        )

    def test_loads_accepts_permissions(self):
        schema = SecretSchema()
        with pytest.raises(ValidationError):
            schema.loads('{"name": "monty", "secret": "shh"}')
        assert schema.loads(
            '{"name": "monty", "secret": "shh"}', permissions="secret"
        ) == {"name": "monty", "secret": "shh"}
