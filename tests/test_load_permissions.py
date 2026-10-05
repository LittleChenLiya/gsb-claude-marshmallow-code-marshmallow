"""Tests for the explicit per-load permission context.

Fields declare required permissions via ``load_permissions=(...)``; callers
grant permissions per call via ``Schema.load(..., permissions={...})``.

Run with::

    python -m pytest tests/test_load_permissions.py -v
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from marshmallow import Schema, ValidationError, fields


class CountingField(fields.Field):
    """A field that counts how many times its deserializer runs.

    The counter is a class attribute because schemas deep-copy their declared
    fields when binding them; the original instance is not the one invoked.
    """

    deserialize_calls = 0

    def _deserialize(self, value, attr, data, **kwargs):
        CountingField.deserialize_calls += 1
        return f"converted:{value}"


@pytest.fixture(autouse=True)
def reset_counting_field():
    CountingField.deserialize_calls = 0


def make_schema_class():
    class SecretSchema(Schema):
        name = fields.Str()
        secret = CountingField(load_permissions=("secret.read",))

    return SecretSchema


class TestLoadPermissions:
    def test_unauthorized_field_rejected_before_deserialize(self):
        SecretSchema = make_schema_class()
        schema = SecretSchema()
        with pytest.raises(ValidationError) as excinfo:
            schema.load({"name": "alice", "secret": "s3cr3t"})
        assert "secret" in excinfo.value.messages
        # The custom deserializer must not have run at all.
        assert CountingField.deserialize_calls == 0

    def test_authorized_field_is_deserialized(self):
        SecretSchema = make_schema_class()
        schema = SecretSchema()
        result = schema.load(
            {"name": "alice", "secret": "s3cr3t"}, permissions={"secret.read"}
        )
        assert result["secret"] == "converted:s3cr3t"
        assert CountingField.deserialize_calls == 1

    def test_partial_permission_grant_is_denied(self):
        SecretSchema = make_schema_class()
        schema = SecretSchema()
        with pytest.raises(ValidationError) as excinfo:
            schema.load({"secret": "s3cr3t"}, permissions={"other.perm"})
        assert "secret" in excinfo.value.messages
        assert CountingField.deserialize_calls == 0

    def test_missing_field_does_not_trigger_permission_error(self):
        SecretSchema = make_schema_class()
        schema = SecretSchema()
        # No permissions granted, but the field is absent from the input.
        result = schema.load({"name": "alice"})
        assert result == {"name": "alice"}
        assert CountingField.deserialize_calls == 0

    def test_error_message_does_not_leak_input_value(self):
        SecretSchema = make_schema_class()
        schema = SecretSchema()
        with pytest.raises(ValidationError) as excinfo:
            schema.load({"secret": "super-secret-value"})
        assert "super-secret-value" not in str(excinfo.value.messages)

    def test_dump_only_field_follows_original_rules(self):
        class DumpOnlySchema(Schema):
            name = fields.Str()
            computed = fields.Str(dump_only=True, load_permissions=("computed.read",))

        schema = DumpOnlySchema()
        # dump_only fields are skipped on load per the original rules; the
        # permission check must not fire for them either.
        result = schema.load(
            {"name": "alice", "computed": "ignored"}, unknown="exclude"
        )
        assert result == {"name": "alice"}

    def test_sequential_loads_do_not_leak_permissions(self):
        SecretSchema = make_schema_class()
        schema = SecretSchema()
        # Authorized load succeeds...
        result = schema.load({"secret": "s3cr3t"}, permissions={"secret.read"})
        assert result["secret"] == "converted:s3cr3t"
        # ...but the next load on the same schema is unauthorized again.
        with pytest.raises(ValidationError) as excinfo:
            schema.load({"secret": "s3cr3t"})
        assert "secret" in excinfo.value.messages
        assert CountingField.deserialize_calls == 1

    def test_concurrent_loads_are_isolated(self):
        SecretSchema = make_schema_class()
        schema = SecretSchema()

        def authorized_load():
            return schema.load({"secret": "x"}, permissions={"secret.read"})

        def unauthorized_load():
            try:
                schema.load({"secret": "x"})
            except ValidationError:
                return "denied"
            return "allowed"

        with ThreadPoolExecutor(max_workers=8) as pool:
            authorized = list(pool.map(lambda _: authorized_load(), range(20)))
            unauthorized = list(pool.map(lambda _: unauthorized_load(), range(20)))
        assert all(r["secret"] == "converted:x" for r in authorized)
        assert all(r == "denied" for r in unauthorized)

    def test_schema_state_is_not_mutated(self):
        secret_field = CountingField(load_permissions=("secret.read",))

        class SecretSchema(Schema):
            secret = secret_field

        schema = SecretSchema()
        schema.load({"secret": "x"}, permissions={"secret.read"})
        with pytest.raises(ValidationError):
            schema.load({"secret": "x"})
        # Declared permissions are unchanged and no context leaks onto the
        # schema or field objects.
        assert secret_field.load_permissions == frozenset({"secret.read"})
        assert not hasattr(schema, "permissions")
        assert not hasattr(schema, "_permissions")


class TestNestedLoadPermissions:
    def make_schemas(self):
        class InnerSchema(Schema):
            name = fields.Str()
            secret = CountingField(load_permissions=("secret.read",))

        class OuterSchema(Schema):
            title = fields.Str()
            inner = fields.Nested(InnerSchema)

        class OuterListSchema(Schema):
            inners = fields.List(fields.Nested(InnerSchema))

        class OuterManySchema(Schema):
            inner = fields.Nested(InnerSchema, many=True)

        return OuterSchema, OuterListSchema, OuterManySchema

    def test_nested_field_inherits_permission_context(self):
        OuterSchema, _, _ = self.make_schemas()
        schema = OuterSchema()
        with pytest.raises(ValidationError) as excinfo:
            schema.load({"title": "t", "inner": {"name": "n", "secret": "s"}})
        assert excinfo.value.messages == {"inner": {"secret": ["Permission denied."]}}
        assert CountingField.deserialize_calls == 0

        result = schema.load(
            {"title": "t", "inner": {"name": "n", "secret": "s"}},
            permissions={"secret.read"},
        )
        assert result["inner"]["secret"] == "converted:s"
        assert CountingField.deserialize_calls == 1

    def test_nested_missing_field_does_not_trigger_permission_error(self):
        OuterSchema, _, _ = self.make_schemas()
        schema = OuterSchema()
        result = schema.load({"title": "t", "inner": {"name": "n"}})
        assert result == {"title": "t", "inner": {"name": "n"}}
        assert CountingField.deserialize_calls == 0

    def test_list_of_nested_inherits_permission_context(self):
        _, OuterListSchema, _ = self.make_schemas()
        schema = OuterListSchema()
        with pytest.raises(ValidationError) as excinfo:
            schema.load({"inners": [{"secret": "a"}, {"name": "b"}]})
        assert excinfo.value.messages == {
            "inners": {0: {"secret": ["Permission denied."]}}
        }
        assert CountingField.deserialize_calls == 0

        result = schema.load(
            {"inners": [{"secret": "a"}, {"name": "b"}]},
            permissions={"secret.read"},
        )
        assert result["inners"][0]["secret"] == "converted:a"
        assert CountingField.deserialize_calls == 1

    def test_nested_many_inherits_permission_context(self):
        _, _, OuterManySchema = self.make_schemas()
        schema = OuterManySchema()
        with pytest.raises(ValidationError) as excinfo:
            schema.load({"inner": [{"secret": "a"}, {"secret": "b"}]})
        assert "inner" in excinfo.value.messages
        assert CountingField.deserialize_calls == 0

        result = schema.load(
            {"inner": [{"secret": "a"}, {"secret": "b"}]},
            permissions={"secret.read"},
        )
        assert [r["secret"] for r in result["inner"]] == [
            "converted:a",
            "converted:b",
        ]
        assert CountingField.deserialize_calls == 2

    def test_many_schema_load_inherits_permission_context(self):
        secret_field = CountingField(load_permissions=("secret.read",))

        class ItemSchema(Schema):
            secret = secret_field

        schema = ItemSchema(many=True)
        with pytest.raises(ValidationError):
            schema.load([{"secret": "a"}, {"secret": "b"}])
        assert CountingField.deserialize_calls == 0

        result = schema.load(
            [{"secret": "a"}, {"secret": "b"}], permissions={"secret.read"}
        )
        assert [r["secret"] for r in result] == ["converted:a", "converted:b"]
        assert CountingField.deserialize_calls == 2


class TestLoadPermissionsApi:
    def test_loads_accepts_permissions(self):
        SecretSchema = make_schema_class()
        schema = SecretSchema()
        with pytest.raises(ValidationError):
            schema.loads('{"secret": "s3cr3t"}')
        assert CountingField.deserialize_calls == 0
        result = schema.loads('{"secret": "s3cr3t"}', permissions={"secret.read"})
        assert result["secret"] == "converted:s3cr3t"

    def test_validate_reports_permission_errors(self):
        SecretSchema = make_schema_class()
        schema = SecretSchema()
        errors = schema.validate({"secret": "s3cr3t"})
        assert errors == {"secret": ["Permission denied."]}
        assert CountingField.deserialize_calls == 0
        assert schema.validate({"secret": "s3cr3t"}, permissions={"secret.read"}) == {}

    def test_permissions_accepted_as_any_iterable(self):
        SecretSchema = make_schema_class()
        schema = SecretSchema()
        result = schema.load({"secret": "x"}, permissions=["secret.read"])
        assert result["secret"] == "converted:x"

    def test_multiple_declared_permissions_require_all(self):
        class MultiSchema(Schema):
            secret = CountingField(load_permissions=("perm.a", "perm.b"))

        schema = MultiSchema()
        with pytest.raises(ValidationError):
            schema.load({"secret": "x"}, permissions={"perm.a"})
        result = schema.load({"secret": "x"}, permissions={"perm.a", "perm.b"})
        assert result["secret"] == "converted:x"
