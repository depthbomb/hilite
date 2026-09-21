import json
from typing import Any


def loads_jsonc(source: str) -> Any:
    without_comments = _strip_comments(source)
    return json.loads(_strip_trailing_commas(without_comments))


def _strip_comments(source: str) -> str:
    output = []
    index = 0
    in_string = False
    escaped = False
    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ''
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == '/' and following == '/':
            output.extend('  ')
            index += 2
            while index < len(source) and source[index] not in '\r\n':
                output.append(' ')
                index += 1
            continue
        if character == '/' and following == '*':
            output.extend('  ')
            index += 2
            while index < len(source):
                if source[index : index + 2] == '*/':
                    output.extend('  ')
                    index += 2
                    break
                output.append(source[index] if source[index] in '\r\n' else ' ')
                index += 1
            else:
                raise ValueError('unterminated block comment in JSON')
            continue
        output.append(character)
        index += 1
    return ''.join(output)


def _strip_trailing_commas(source: str) -> str:
    output = []
    index = 0
    in_string = False
    escaped = False
    while index < len(source):
        character = source[index]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == ',':
            cursor = index + 1
            while cursor < len(source) and source[cursor].isspace():
                cursor += 1
            if cursor < len(source) and source[cursor] in ']}':
                index += 1
                continue
        output.append(character)
        index += 1
    return ''.join(output)
