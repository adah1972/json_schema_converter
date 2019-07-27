#!/usr/bin/env python3

# Copyright (C) 2019 Wu Yongwei <wuyongwei at gmail dot com>
#
# This software is provided 'as-is', without any express or implied
# warranty.  In no event will the author be held liable for any damages
# arising from the use of this software.
#
# Permission is granted to anyone to use this software for any purpose,
# including commercial applications, and to alter it and redistribute it
# freely, subject to the following restrictions:
#
# 1. The origin of this software must not be misrepresented; you must not
#    claim that you wrote the original software.  If you use this software
#    in a product, an acknowledgement in the product documentation would
#    be appreciated but is not required.
# 2. Altered source versions must be plainly marked as such, and must not
#    be misrepresented as being the original software.
# 3. This notice may not be removed or altered from any source
#    distribution.

import copy
import getopt
import json
import sys


JSON_SCHEMA_TYPES = [
    'string',
    'number',
    'boolean',
    'null',
    'object',
    'array',
    'integer',
]
MONGO_BSON_TYPES = [
    'string',
    'number',
    'bool',
    'null',
    'object',
    'array',
    'int',
    'long',
    'double',
    'date',
    'timestamp',
    'objectId',
    'binData',
]
BUILTIN_DEFINITIONS = {
    "objectId": {
        "type": "object",
        "required": ["$oid"],
        "additionalProperties": False,
        "properties": {
            "$oid": {
                "type": "string",
                "pattern": "^[0-9A-Fa-f]{24}$"
            }
        }
    },
    "date": {
        "type": "object",
        "required": ["$date"],
        "additionalProperties": False,
        "properties": {
            "$date": {
                "type": "string",
                "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}"
                           "T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{3})?Z$"
            }
        }
    },
    "binData": {
        "type": "object",
        "required": ["$binary", "$type"],
        "additionalProperties": False,
        "properties": {
            "$binary": {
                "type": "string",
                "pattern": "^[=0-9A-Za-z+/]*$"
            },
            "$type": {
                "type": "string",
                "pattern": "^[0-9A-Za-z]{1,2}$"
            }
        }
    },
    "coordinates": {
        "type": "array",
        "items": {
            "anyOf": [
                {"type": "number"},
                {"type": "coordinates"}
            ]
        }
    },
    "geoJson": {
        "type": "object",
        "required": ["type", "coordinates"],
        "additionalProperties": False,
        "properties": {
            "type": {
                "type": "string",
                "enum": ["Point", "MultiPoint",
                         "LineString", "MultiLineString",
                         "Polygon", "MultiPolygon"]
            },
            "coordinates": {"type": "coordinates"}
        }
    }
}


class UnknownTypeError(RuntimeError):
    def __init__(self, msg, type_name):
        super().__init__(msg)
        self.type_name = type_name


class SchemaConverter:
    def __init__(self, schema, make_copy=False):
        if make_copy:
            self.schema = copy.deepcopy(schema)
        else:
            self.schema = schema
        self.definitions = {}
        self.result = {}
        self.ready = False

    def get_result(self):
        if not self.ready:
            self.generate_result()
        return self.result

    def generate_result(self):
        raise NotImplementedError('generate_result requires overriding')

    def convert_object(self, object_, src_path, obj_path):
        if not isinstance(object_, dict):
            raise RuntimeError(
                'Non-object type encountered when parsing ' + src_path)
        result = {}
        if not src_path.endswith('/'):
            src_path += '/'
        for k, v in object_.items():
            if k in ['definitions', 'properties']:
                v = self.convert_inner_type(v, src_path + k, obj_path)
            elif k in ['allOf', 'anyOf', 'oneOf', 'not']:
                v = self.convert_array(v, src_path + k, obj_path)
            elif k == 'items':
                v = self.convert_object(v, src_path + k, obj_path)
            elif k == 'type':
                result.update(self.convert_type(v, src_path + k, obj_path))
                continue
            result[k] = v
        return result

    def convert_array(self, array, src_path, obj_path):
        if not isinstance(array, list):
            raise RuntimeError(
                'Non-array type encountered when parsing ' + src_path)
        result = []
        for i, v in enumerate(array):
            result.append(self.convert_object(
                v, src_path + '[' + str(i) + ']', obj_path))
        return result

    def convert_inner_type(self, object_, src_path, obj_path):
        if not isinstance(object_, dict):
            raise RuntimeError(
                'Non-object type encountered when parsing ' + src_path)
        result = {}
        if not src_path.endswith('/'):
            src_path += '/'
        for k, v in object_.items():
            result[k] = self.convert_object(v, src_path + k, obj_path + [k])
        return result

    def convert_type(self, type_, src_path, obj_path):
        raise NotImplementedError('convert_type requires overriding')


class Draft4Converter(SchemaConverter):
    def __init__(self, schema, make_copy=False):
        super().__init__(schema, make_copy)
        self.result = {
            "$schema": "http://json-schema.org/draft-04/schema#"
        }
        self.type_dependencies = {}
        self.used_types = set()

    def generate_result(self):
        if self.ready:
            return
        self.definitions = BUILTIN_DEFINITIONS.copy()
        if 'definitions' in self.schema:
            self.definitions.update(self.schema['definitions'])
            del self.schema['definitions']
        self.definitions = self.convert_inner_type(
            self.definitions, '/definitions', ['$definitions'])
        result = self.convert_object(self.schema, '/', [])
        self.remove_unused_definitions()
        if self.definitions:
            self.result['definitions'] = self.definitions
        self.result.update(result)
        self.ready = True

    def convert_type(self, type_, src_path, obj_path):
        if not isinstance(type_, str):
            raise RuntimeError(
                'Non-string type encountered when parsing ' + src_path)
        if type_ in ['double', 'int', 'long', 'decimal']:
            return {"type": "number"}
        if type_ in JSON_SCHEMA_TYPES:
            return {"type": type_}
        if type_ in self.definitions:
            self.record_dependency(type_, obj_path)
            return {"$ref": '#/definitions/' + type_}
        raise UnknownTypeError(
            'Unrecognized type "{}" encountered when parsing {}'.format(
                type_, src_path), type_)

    def record_dependency(self, type_, obj_path):
        if obj_path and obj_path[0] == '$definitions':
            depender = obj_path[1]
            self.type_dependencies.setdefault(depender, set())
            if depender != type_:
                self.type_dependencies[depender].add(type_)
        else:
            self.record_type_usage(type_)

    def record_type_usage(self, type_):
        if type_ not in self.used_types:
            if type_ in self.type_dependencies:
                for dependee_type in self.type_dependencies[type_]:
                    self.record_type_usage(dependee_type)
            self.used_types.add(type_)

    def remove_unused_definitions(self):
        to_remove = [type_ for type_ in self.definitions
                     if type_ not in self.used_types]
        for type_ in to_remove:
            del self.definitions[type_]


class Mongo36Converter(SchemaConverter):
    def generate_result(self):
        if self.ready:
            return
        definitions = BUILTIN_DEFINITIONS.copy()
        if 'definitions' in self.schema:
            definitions.update(self.schema['definitions'])
            del self.schema['definitions']
        self.parse_definitions(definitions)
        result = self.convert_object(self.schema, '/', [])
        self.result['$jsonSchema'] = result
        self.ready = True

    def parse_definitions(self, definitions):
        assert isinstance(definitions, dict)
        src_path = '/definitions/'
        for k, v in definitions.items():
            try:
                self.definitions[k] = self.convert_object(v, src_path + k,
                                                          ['$definitions'])
            except UnknownTypeError as e:
                if e.type_name != k:
                    raise
                if not isinstance(v, dict) and 'type' in v:
                    raise RuntimeError('Wrong definition in type ' + k)
                self.definitions[k] = {"type": v['type']}

    def convert_type(self, type_, src_path, obj_path):
        if not isinstance(type_, str):
            raise RuntimeError(
                'Non-string type encountered when parsing ' + src_path)
        if type_ == 'integer':
            return {"bsonType": "int"}
        if type_ in JSON_SCHEMA_TYPES:
            return {"type": type_}
        if type_ in MONGO_BSON_TYPES:
            return {"bsonType": type_}
        if type_ in self.definitions:
            return self.definitions[type_]
        raise UnknownTypeError(
            'Unrecognized type "{}" encountered when parsing {}'.format(
                type_, src_path), type_)


class Mongo32Converter(Mongo36Converter):
    def generate_result(self):
        if self.ready:
            return
        definitions = BUILTIN_DEFINITIONS.copy()
        if 'definitions' in self.schema:
            definitions.update(self.schema['definitions'])
            del self.schema['definitions']
        self.parse_definitions(definitions)
        self.definitions = self.convert_inner_type(
            definitions, '/definitions', ['definitions'])
        result = self.convert_object(self.schema, '/', [])
        self.flatten_result(result)
        self.ready = True

    def flatten_result(self, result):
        Mongo32Converter._flatten_recursively(result, self.result, [])

    @staticmethod
    def _flatten_recursively(result, flattened_result, obj_path):
        required_properties = result.get('required', [])
        for item in required_properties:
            stringized_path = '.'.join(obj_path + [item])
            flattened_result.setdefault(stringized_path, {})
            flattened_result[stringized_path]['$exists'] = True

        stringized_path = '.'.join(obj_path)
        if stringized_path and stringized_path in flattened_result:
            need_exists = True
            if 'bsonType' in result:
                flattened_result[stringized_path]['$type'] = result['bsonType']
                need_exists = False
            elif 'type' in result:
                flattened_result[stringized_path]['$type'] = result['type']
                need_exists = False
            if 'pattern' in result:
                flattened_result[stringized_path]['$regex'] = result['pattern']
                need_exists = False
            if 'enum' in result:
                flattened_result[stringized_path]['$in'] = result['enum']
                need_exists = False
            if '$exists' in flattened_result[stringized_path] and \
                    not need_exists:
                del flattened_result[stringized_path]['$exists']
        if 'properties' in result:
            for k, v in result['properties'].items():
                if k in required_properties:
                    Mongo32Converter._flatten_recursively(
                        v, flattened_result, obj_path + [k])


def convert_schema(in_file, out_file, target_type):
    schema = json.load(in_file)
    class_table = {
        "draft4": Draft4Converter,
        "mongo32": Mongo32Converter,
        "mongo36": Mongo36Converter,
    }
    try:
        converter = class_table[target_type](schema)
    except KeyError:
        raise RuntimeError('Unrecognized target type ' + target_type)
    result = converter.get_result()
    json.dump(result, out_file, ensure_ascii=False, indent=2)
    print('')


def usage():
    print('Usage: {} [options] [input file]'.format(sys.argv[0]))
    print("""
Options
  -h, --help              Show this message and exit')
  -t, --type TARGET_TYPE  Specify the target type, possible values being
                          draft4 (default), mongo32, and mongo36

When the input file is not provided, stdin is used.
""")


def main():
    try:
        opts, args = getopt.getopt(sys.argv[1:], "ht:", ["help", "type="])
    except getopt.GetoptError as err:
        print(str(err))
        usage()
        sys.exit(2)

    if len(args) >= 2:
        print('At most one file name can be provided', file=sys.stderr)
        sys.exit(2)

    target_type = 'draft4'
    for opt, arg in opts:
        if opt in ['-h', '--help']:
            usage()
            sys.exit()
        elif opt in ['-t', '--type']:
            target_type = arg

    if args:
        input_file = open(args[0], 'r')
    else:
        input_file = sys.stdin

    try:
        convert_schema(input_file, sys.stdout, target_type)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    finally:
        if args:
            input_file.close()


if __name__ == '__main__':
    main()
