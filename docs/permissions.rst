*******************
Load permissions
*******************

marshmallow supports an explicit, per-load permission context. Fields declare
the permissions they require, and a load is granted a set of permissions.
Fields whose required permissions are not granted are rejected **before**
their deserializers run.

Declaring permissions on a field
=================================

Use the ``permissions`` argument on any field to declare the permission (or
permissions) required to load that field. A single string or a collection of
strings is accepted.

.. code-block:: python

    from marshmallow import Schema, fields


    class UserSchema(Schema):
        name = fields.Str()
        email = fields.Email(permissions="read")
        secret = fields.Str(permissions=("read", "secret"))

``permissions`` only affects deserialization (``load``). It has no effect on
serialization (``dump``).

Granting permissions for a load
===============================

Pass the ``permissions`` argument to `Schema.load <marshmallow.Schema.load>`
(or `Schema.loads <marshmallow.Schema.loads>`) to grant permissions for that
load. The context is **per-load**: it is passed as an argument and is never
stored on the schema or its fields, so consecutive or concurrent loads cannot
leak permissions into one another.

.. code-block:: python

    schema = UserSchema()

    # No permissions: ``email`` and ``secret`` are rejected before their
    # deserializers run.
    schema.load({"name": "monty", "email": "m@example.com", "secret": "shh"})
    # ValidationError: {'email': ['You do not have permission to load this field.'],
    #                    'secret': ['You do not have permission to load this field.']}

    # Grant permissions for this load only.
    schema.load(
        {"name": "monty", "email": "m@example.com", "secret": "shh"},
        permissions=("read", "secret"),
    )
    # {'name': 'monty', 'email': 'm@example.com', 'secret': 'shh'}

A field that declares multiple permissions requires **all** of them to be
granted.

Missing fields are not rejected
===============================

A field that is absent from the input is never rejected for missing
permissions. The permission check only runs when a value is present, so a
field with a ``load_default`` is also unaffected.

.. code-block:: python

    # ``secret`` is missing, so no permission error is raised.
    UserSchema().load({"name": "monty"})
    # {'name': 'monty'}

``dump_only`` fields follow their original rules and are skipped during
deserialization regardless of any declared permissions.

Nested fields and collections
=============================

The permission context propagates down through `Nested <marshmallow.fields.Nested>`
fields and collection fields (`List <marshmallow.fields.List>`,
`Tuple <marshmallow.fields.Tuple>`, `Dict <marshmallow.fields.Dict>`) along
the sub-path, so fields at any nesting depth are checked. A ``Nested`` field
can also declare its own permissions to gate the entire nested object.

.. code-block:: python

    class ChildSchema(Schema):
        name = fields.Str()
        secret = fields.Str(permissions="secret")


    class ParentSchema(Schema):
        child = fields.Nested(ChildSchema)
        children = fields.List(fields.Nested(ChildSchema))


    parent = ParentSchema()

    # No permissions: the nested ``secret`` fields are rejected.
    parent.load(
        {
            "child": {"name": "a", "secret": "shh"},
            "children": [{"name": "b", "secret": "shh"}],
        }
    )

    # Grant permissions for the load; the context propagates to every level.
    parent.load(
        {
            "child": {"name": "a", "secret": "shh"},
            "children": [{"name": "b", "secret": "shh"}],
        },
        permissions="secret",
    )

The same applies to ``many=True`` on `Schema.load <marshmallow.Schema.load>`,
`Pluck <marshmallow.fields.Pluck>`, and `Schema.validate <marshmallow.Schema.validate>`.

Error messages
==============

When a field is rejected, the error message is the field's
``permission_denied`` message. The input value is **never** included in the
message, so sensitive values cannot leak through validation errors. The
default message is:

    You do not have permission to load this field.

It can be overridden per field via the ``error_messages`` argument:

.. code-block:: python

    fields.Str(
        permissions="secret",
        error_messages={"permission_denied": "No access to this field."},
    )

Running the tests
=================

The permission tests live in ``tests/test_permissions.py``. Run them with:

.. code-block:: shell

    $ pytest tests/test_permissions.py -q

To run the full test suite:

.. code-block:: shell

    $ pytest -q
