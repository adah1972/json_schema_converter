# JSON Schema Converter

## Problems

[JSON Schema][1] provides a useful way to validate JSON data. However,
[MongoDB][2] supports only a subset of JSON Schema specification draft
4. Specifically, [definitions and references are left out][3] (as of 28
July 2019). MongoDB 3.2 and 3.4 does not even support JSON Schema, but
only a [MongoDB-proprietary validation method][4]. Besides, [MongoDB has
a richer type system than JSON Schema][5]. . . .

[1]: https://json-schema.org/
[2]: https://www.mongodb.com/
[3]: https://docs.mongodb.com/manual/reference/operator/query/jsonSchema/#json-schema-omission
[4]: https://docs.mongodb.com/v3.2/core/document-validation/
[5]: https://docs.mongodb.com/manual/reference/operator/query/type/#document-type-available-types

## Solution

### One input, multiple outputs

My decision is that all my schemas should take the same format, but can
be converted to serve different purposes. I also decide that all types
should be treated equally, so a custom type will be referenced simply as
`"type": "MyType"`, instead of `"$ref": "…"` (or `"bsonType": "…"`, as
MongoDB requires). Apart from that, the input format conforms to JSON
Schema (draft 4). This will allow people to write simply `"type":
"objectId"` when the MongoDB BSON type ObjectId is intended.

### Example

An input (assume it is named *test.json*):

```json
{
  "type": "object",
  "required": ["_id", "name", "gender"],
  "properties": {
    "_id": {
      "type": "objectId"
    },
    "name": {
      "type": "string",
      "maxLength": 80
    },
    "gender": {
      "type": "string",
      "enum": ["male", "female", "ambiguous", "unknown"]
    },
    "age": {
      "type": "number"
    }
  },
  "additionalProperties": false
}
```

---

Output with `./convert_schema.py -t draft4 test.json` (`-t draft4` can
be omitted, as it is the default):

```json
{
  "$schema": "http://json-schema.org/draft-04/schema#",
  "definitions": {
    "objectId": {
      "type": "object",
      "required": [
        "$oid"
      ],
      "additionalProperties": false,
      "properties": {
        "$oid": {
          "type": "string",
          "pattern": "^[0-9A-Fa-f]{24}$"
        }
      }
    }
  },
  "type": "object",
  "required": [
    "_id",
    "name",
    "gender"
  ],
  "properties": {
    "_id": {
      "$ref": "#/definitions/objectId"
    },
    "name": {
      "type": "string",
      "maxLength": 80
    },
    "gender": {
      "type": "string",
      "enum": [
        "male",
        "female",
        "ambiguous",
        "unknown"
      ]
    },
    "age": {
      "type": "number"
    }
  },
  "additionalProperties": false
}
```

(You can see that `"type": "objectId"` is changed to `"$ref":
"#/definitions/objectId"`, and a definition of `objectId`—included
in my script—is generated automatically. Of course, you can add
your own definitions too.)

---

Output with `./convert_schema.py -t mongo36 test.json`:

```json
{
  "$jsonSchema": {
    "bsonType": "object",
    "required": [
      "_id",
      "name",
      "gender"
    ],
    "properties": {
      "_id": {
        "bsonType": "objectId"
      },
      "name": {
        "bsonType": "string",
        "maxLength": 80
      },
      "gender": {
        "bsonType": "string",
        "enum": [
          "male",
          "female",
          "ambiguous",
          "unknown"
        ]
      },
      "age": {
        "bsonType": "number"
      }
    },
    "additionalProperties": false
  }
}
```

(You can see that `"type"` is changed to `"bsonType"`—for consistency,
although only necessary for types not present in standard JSON—and the
whole thing is wrapped in a `$jsonSchema` field for easy use with
MongoDB.)

---

Output with `./convert_schema.py -t mongo32 test.json` (only basic
support for this target type is implemented, as MongoDB 3.4 will soon
reach its end of life):

```json
{
  "_id": {
    "$type": "objectId"
  },
  "name": {
    "$type": "string"
  },
  "gender": {
    "$type": "string",
    "$in": [
      "male",
      "female",
      "ambiguous",
      "unknown"
    ]
  }
}
```

### Expanding definitions for ‘mongo36’

One major shortcoming of the MongoDB schema validation is that
**definitions** and **$ref** are not supported. My converter supports
definition expansion for the ‘mongo36’ target. Of course, recursive
types have to be crippled.

My converter has the `geoJson` definition built in. It is defined as
follows (please notice the recursive definition of `coordinates`):

```json
{
  "definitions": {
    "coordinates": {
      "type": "array",
      "items": {
        "anyOf": [
          {
            "type": "number"
          },
          {
            "$ref": "#/definitions/coordinates"
          }
        ]
      }
    },
    "geoJson": {
      "type": "object",
      "required": [
        "type",
        "coordinates"
      ],
      "additionalProperties": false,
      "properties": {
        "type": {
          "type": "string",
          "enum": [
            "Point",
            "MultiPoint",
            "LineString",
            "MultiLineString",
            "Polygon",
            "MultiPolygon"
          ]
        },
        "coordinates": {
          "$ref": "#/definitions/coordinates"
        }
      }
    }
  }
}
```

If a location was described this way:

```json
{
  "properties": {
    "location": {
      "type": "geoJson"
    }
  }
}
```

The ‘draft4’ output would be:

```json
{
  "properties": {
    "location": {
      "$ref": "#/definitions/geoJson"
    }
  }
}
```

The ‘mongo36’ output would be:

```json
{
  "properties": {
    "location": {
      "bsonType": "object",
      "required": [
        "type",
        "coordinates"
      ],
      "additionalProperties": false,
      "properties": {
        "type": {
          "bsonType": "string",
          "enum": [
            "Point",
            "MultiPoint",
            "LineString",
            "MultiLineString",
            "Polygon",
            "MultiPolygon"
          ]
        },
        "coordinates": {
          "bsonType": "array"
        }
      }
    }
  }
}
```

### A last notice

An input may be valid for one target type but not for another. For
example, I do not use the BSON type *Timestamp*, and my converter does
not include special support for it (though it can be done quite
trivially): while a schema containing the type `timestamp` can be
converted targeting ‘mongo32’/‘mongo36’, it will fail when targeting
‘draft4’.

## System requirements

For simplicity, the code is written for Python 3.6+ only. No additional
packages are needed.

## Licence

Copyright © 2019 Wu Yongwei.

This software is provided ‘as-is’, without any express or implied
warranty. In no event will the author be held liable for any damages
arising from the use of this software. Permission is granted to anyone
to use this software for any purpose, including commercial applications,
and to alter it and redistribute it freely, subject to the following
restrictions:

1. The origin of this software must not be misrepresented; you must not
   claim that you wrote the original software. If you use this software
   in a product, an acknowledgement in the product documentation would
   be appreciated but is not required.
2. Altered source versions must be plainly marked as such, and must not
   be misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.
