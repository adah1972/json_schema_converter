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
# 1. The origin of this software must not be misrepresented; you must
#    not claim that you wrote the original software.  If you use this
#    software in a product, an acknowledgement in the product
#    documentation would be appreciated but is not required.
# 2. Altered source versions must be plainly marked as such, and must
#    not be misrepresented as being the original software.
# 3. This notice may not be removed or altered from any source
#    distribution.

import getopt
import json
import sys
from typing import Any, Dict, List, Set, TextIO


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
    "alt_definitions": {
        "json": {
            "binData": {
                "type": "object",
                "required": ["$binary", "$type"],
                "properties": {
                    "$binary": {
                        "type": "string",
                        "pattern": "^[=0-9A-Za-z+/]*$"
                    },
                    "$type": {
                        "type": "string",
                        "pattern": "^[0-9A-Za-z]{1,2}$"
                    }
                },
                "additionalProperties": False
            },
            "date": {
                "type": "object",
                "required": ["$date"],
                "properties": {
                    "$date": {
                        "type": "string",
                        "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
                                   "[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{3})?Z$"
                    }
                },
                "additionalProperties": False
            },
            "objectId": {
                "type": "object",
                "required": ["$oid"],
                "properties": {
                    "$oid": {
                        "type": "string",
                        "pattern": "^[0-9A-Fa-f]{24}$"
                    }
                },
                "additionalProperties": False
            },
        }
    }
}


class UnknownTypeError(RuntimeError):
    """
    Type for the unknown type error.

    Attributes
    ----------
    type_name : str
        the name of the unknown type
    """
    def __init__(self, msg, type_name):
        """
        Constructs an UnknownTypeError object.

        Parameters
        ----------
        msg : str
            message to be passed to RuntimeError
        type_name : str
            the name of the unknown type
        """
        super().__init__(msg)
        self.type_name = type_name


class SchemaConverter:
    """
    Class for a generic JSON Schema converter.

    Attributes
    ----------
    schema : dict
        the schema to be converted (it might be changed)
    definitions : dict
        type definitions
    _result : dict
        the result after the conversion
    _ready : bool
        whether the result is ready
    _type : str
        type of the converter (for alternative definitions)
    """
    def __init__(self, schema, definitions=None, type_=None):
        """
        Constructs a SchemaConverter.

        Parameters
        ----------
        schema : Dict[str, Any]
            the input schema
        definitions : Dict[str, Any], optional
            the definitions to use (apart from those in the schema)
        type_ : str, optional
            type of the converter (for alternative definitions)
        """
        self.schema = schema.copy()
        self.definitions = {}
        if definitions:
            _merge_definitions(self.definitions, definitions, type_)
        self._result: Dict[str, Any] = {}
        self._ready = False
        self._type = type_

    @property
    def result(self):
        """
        Gets the result.

        Returns
        -------
        Dict[str, Any]
            the converted result
        """
        if not self._ready:
            self.generate_result()
        return self._result

    def generate_result(self):
        """
        Generates the result if it is not yet ready.
        """
        if self._ready:
            return
        _merge_definitions(self.definitions, self.schema, self._type)
        if 'definitions' in self.schema:
            del self.schema['definitions']
        if 'alt_definitions' in self.schema:
            del self.schema['alt_definitions']
        self.process_definitions()
        self.prepare_result()
        self._ready = True

    def process_definitions(self) -> None:
        """
        Processes the definitions.
        """
        raise NotImplementedError('process_definitions requires overriding')

    def prepare_result(self) -> None:
        """
        Prepares the result.
        """
        raise NotImplementedError('prepare_result requires overriding')

    def convert_object(self, object_, src_path, obj_path):
        """
        Converts an object in a JSON schema.

        Parameters
        ----------
        object_ : dict
            the object to be converted
        src_path : str
            the slash-separated path of the source JSON
        obj_path : List[str]
            the node path of the JSON to be validated

        Returns
        -------
        Dict[str, Any]
            the converted result
        """
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
        """
        Converts an array in a JSON schema.

        Parameters
        ----------
        array : List[dict]
            the array to be converted
        src_path : str
            the slash-separated path of the source JSON
        obj_path : List[str]
            the node path of the JSON to be validated

        Returns
        -------
        List[Dict[str, Any]]
            the converted result
        """
        if not isinstance(array, list):
            raise RuntimeError(
                'Non-array type encountered when parsing ' + src_path)
        result = []
        for i, v in enumerate(array):
            result.append(self.convert_object(
                v, src_path + '[' + str(i) + ']', obj_path))
        return result

    def convert_inner_type(self, object_, src_path, obj_path):
        """
        Converts the inner layer of an object in a JSON schema.

        Parameters
        ----------
        object_ : dict
            the object to be converted
        src_path : str
            the slash-separated path of the source JSON
        obj_path : List[str]
            the node path of the JSON to be validated

        Returns
        -------
        Dict[str, Any]
            the converted result
        """
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
        """
        Converts a type in a JSON schema.

        Parameters
        ----------
        type_ : str
            the type to be converted
        src_path : str
            the slash-separated path of the source JSON
        obj_path : List[str]
            the node path of the JSON to be validated

        Returns
        -------
        Dict[str, Any]
            the converted result
        """
        raise NotImplementedError('convert_type requires overriding')


class Draft4Converter(SchemaConverter):
    """
    Class for a JSON Schema Draft 4 converter.

    The parameter obj_path is mainly only used in this converter for
    the recording of type usage.

    Attributes
    ----------
    type_dependencies : Dict[str, Set[str]]
        key is the type name, and value is a list of dependent types
    used_types : Set[str]
        set of used types
    """
    def __init__(self, schema, definitions):
        super().__init__(schema, definitions, type_='json')
        self._result: Dict[str, Any] = {
            "$schema": "http://json-schema.org/draft-04/schema#"
        }
        self.type_dependencies: Dict[str, Set[str]] = {}
        self.used_types = set()

    def process_definitions(self):
        self.definitions = self.convert_inner_type(
            self.definitions, '/definitions', ['$definitions'])

    def prepare_result(self):
        result = self.convert_object(self.schema, '/', [])
        self.remove_unused_definitions()
        if self.definitions:
            self._result['definitions'] = self.definitions
        self._result.update(result)

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

    def record_dependency(self, type_: str, obj_path: List[str]):
        if obj_path and obj_path[0] == '$definitions':
            depender = obj_path[1]
            self.type_dependencies.setdefault(depender, set())
            if depender != type_:
                self.type_dependencies[depender].add(type_)
        else:
            self.record_type_usage(type_)

    def record_type_usage(self, type_: str):
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
    """
    Class for a schema converter that is compatible with MongoDB 3.6.

    This converter maps a type to bsonType wherever possible, and will
    expand definitions on the result.
    """
    def __init__(self, schema, definitions):
        super().__init__(schema, definitions, type_='mongodb')

    def process_definitions(self):
        src_path = '/definitions/'
        definitions = self.definitions
        self.definitions: Dict[str, Any] = {}
        for k, v in definitions.items():
            try:
                self.definitions[k] = self.convert_object(v, src_path + k,
                                                          ['$definitions'])
            except UnknownTypeError as e:
                if e.type_name != k:
                    raise
                if not isinstance(v, dict) and 'type' in v:
                    raise RuntimeError('Wrong definition in type ' + k)
                self.definitions[k] = self.convert_type(v['type'],
                                                        src_path + k,
                                                        ['$definitions'])

    def prepare_result(self):
        result = self.convert_object(self.schema, '/', [])
        self._result['$jsonSchema'] = result

    def convert_type(self, type_, src_path, obj_path):
        if not isinstance(type_, str):
            raise RuntimeError(
                'Non-string type encountered when parsing ' + src_path)
        if type_ == 'integer':
            return {"bsonType": "int"}
        if type_ == 'boolean':
            return {"bsonType": "bool"}
        if type_ in MONGO_BSON_TYPES:
            return {"bsonType": type_}
        assert type_ not in JSON_SCHEMA_TYPES
        if type_ in self.definitions:
            return self.definitions[type_]
        raise UnknownTypeError(
            'Unrecognized type "{}" encountered when parsing {}'.format(
                type_, src_path), type_)


class Mongo32Converter(Mongo36Converter):
    """
    Class for a schema converter that is compatible with MongoDB 3.2.

    This converter is only a minimal implementation, as pre-3.6 MongoDB
    will reach the end of its life by 2020.
    """
    def prepare_result(self):
        result = self.convert_object(self.schema, '/', [])
        self.flatten_result(result)

    def flatten_result(self, result: Dict[str, Any]):
        Mongo32Converter._flatten_recursively(result, self._result, [])

    @staticmethod
    def _flatten_recursively(result: Dict[str, Any],
                             flattened_result: Dict[str, Dict[str, Any]],
                             obj_path: List[str]):
        required_properties: List[str] = result.get('required', [])
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


def convert_schema(in_file: TextIO, out_file: TextIO,
                   definitions: Dict[str, Any], target_type: str):
    schema = json.load(in_file)
    class_table = {
        "draft4": Draft4Converter,
        "mongo32": Mongo32Converter,
        "mongo36": Mongo36Converter,
    }
    try:
        # No need to make a copy, as `schema` will be discarded soon.
        converter = class_table[target_type](schema, definitions)
    except KeyError:
        raise RuntimeError('Unrecognized target type ' + target_type)
    result = converter.result
    json.dump(result, out_file, ensure_ascii=False, indent=2)
    print('')


def _add_definitions_file(raw_definitions: Dict[str, Any], filename: str):
    with open(filename, 'r') as f:
        new_definitions = json.load(f)
        if 'definitions' in new_definitions:
            raw_definitions.setdefault('definitions', {}).update(
                new_definitions['definitions'])
        if 'alt_definitions' in new_definitions:
            raw_definitions.setdefault('alt_definitions', {})
            for type_, defs in new_definitions['alt_definitions'].items():
                raw_definitions['alt_definitions'].setdefault(type_, {})\
                    .update(defs)


def _merge_definitions(definitions: Dict[str, Any],
                       raw_definitions: Dict[str, Any], type_: str):
    if 'definitions' in raw_definitions:
        definitions.update(raw_definitions['definitions'])
    if 'alt_definitions' in raw_definitions and \
            type_ in raw_definitions['alt_definitions']:
        definitions.update(raw_definitions['alt_definitions'][type_])


def usage():
    print('Usage: {} [options] [input file]'.format(sys.argv[0]))
    print("""
Options
  -h, --help              Show this message and exit
  -d, --def               Specify a definitions file
  -t, --type TARGET_TYPE  Specify the target type, possible values being
                          draft4 (default), mongo32, and mongo36

When the input file is not provided, stdin is used.
""")


def main():
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'hd:t:',
                                   ['help', 'def=', 'type='])
    except getopt.GetoptError as err:
        print(str(err))
        usage()
        sys.exit(2)

    if len(args) >= 2:
        print('At most one file name can be provided', file=sys.stderr)
        sys.exit(2)

    definitions = BUILTIN_DEFINITIONS.copy()
    target_type = 'draft4'
    for opt, arg in opts:
        if opt in ['-h', '--help']:
            usage()
            sys.exit()
        elif opt in ['-d', '--def']:
            _add_definitions_file(definitions, arg)
        elif opt in ['-t', '--type']:
            target_type = arg

    if args:
        input_file = open(args[0], 'r')
    else:
        input_file = sys.stdin

    try:
        convert_schema(input_file, sys.stdout, definitions, target_type)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    finally:
        if args:
            input_file.close()


if __name__ == '__main__':
    main()
