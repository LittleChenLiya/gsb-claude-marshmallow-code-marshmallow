.. _load_permissions:

Load permissions
================

Marshmallow supports an explicit, per-call permission context for
deserialization. Fields declare which permissions they require, and each
``load`` call grants its own set of permissions. A field whose declared
permissions are not granted is rejected *before* its deserializer runs --
even if the input contains a value for it.

Registering permissions on fields
---------------------------------

Pass ``load_permissions`` to any field to register the permission names
required to deserialize it. A field may require several permissions; all of
them must be granted.

.. code-block:: python

    from marshmallow import Schema, fields


    class UserSchema(Schema):
        name = fields.Str()
        # Registering a permission requirement on the "secret" field
        secret = fields.Str(load_permissions=("secret.read",))
        # Multiple permissions: all must be granted
        salary = fields.Float(load_permissions=("hr.read", "finance.read"))

Granting permissions per load
-----------------------------

Grant permissions for a single call with the ``permissions`` argument of
`Schema.load <marshmallow.Schema.load>` (also supported by
`Schema.loads <marshmallow.Schema.loads>` and
`Schema.validate <marshmallow.Schema.validate>`).

.. code-block:: python

    schema = UserSchema()

    # Denied: "secret.read" is not granted. The field's deserializer never
    # runs, and a "Permission denied." error is stored for the field.
    schema.load({"name": "alice", "secret": "s3cr3t"})
    # ValidationError: {"secret": ["Permission denied."]}

    # Allowed: the permission is granted for this call only.
    schema.load({"name": "alice", "secret": "s3cr3t"}, permissions={"secret.read"})
    # => {"name": "alice", "secret": "s3cr3t"}

Behavior notes
--------------

- **Rejected before deserialization.** Unauthorized fields are rejected
  before ``Field.deserialize`` runs, so custom deserialization code never
  sees unauthorized input.
- **Missing fields are not affected.** The permission check only fires when
  the input actually contains a value for the field. Absent fields follow
  the usual ``required``/``load_default`` rules.
- **``dump_only`` fields are unchanged.** They are skipped during
  deserialization per the original rules and never trigger permission
  errors.
- **Errors do not leak input values.** The ``"Permission denied."`` message
  never includes the submitted value.
- **Nested schemas and collections inherit the context.** Permissions are
  propagated by sub-path through ``Nested`` fields, ``List(Nested(...))``,
  ``Nested(..., many=True)``, and ``many=True`` schema loads.
- **The context is call-local.** Granted permissions are frozen into an
  immutable, per-call context. Concurrent or consecutive ``load`` calls on
  the same schema never share or leak permissions, and neither the schema
  nor its fields are mutated.

Running the tests
-----------------

The feature is covered by a dedicated test module:

.. code-block:: bash

    python -m pytest tests/test_load_permissions.py -v
