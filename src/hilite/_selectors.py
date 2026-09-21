import re
from typing import Optional
from functools import lru_cache
from dataclasses import dataclass
from hilite.errors import ThemeError


@dataclass(frozen=True, slots=True)
class Selector:
    operation: str
    children: tuple[Selector, ...] = ()
    path: tuple[tuple[str, bool], ...] = ()

    def score(self, scopes: tuple[str, ...]) -> Optional[tuple[int, ...]]:
        if self.operation == 'path':
            previous: dict[int, tuple[int, ...]] = {}
            for part_number, (name, direct) in enumerate(self.path):
                current = {}
                parts = name.split('.')
                for index, scope in enumerate(scopes):
                    segments = scope.split('.')
                    if len(parts) > len(segments) or any(
                        part != '*' and part != segment
                        for part, segment in zip(parts, segments, strict=False)
                    ):
                        continue
                    parents = [
                        rank
                        for position, rank in previous.items()
                        if position < index and (not direct or position == index - 1)
                    ]
                    if part_number and not parents:
                        continue
                    # Compare the innermost match first; parent matches break ties.
                    current[index] = (
                        index,
                        len(name.replace('*', '')),
                        *(max(parents) if parents else ()),
                    )
                previous = current
            return max(previous.values(), default=None)
        scores = [child.score(scopes) for child in self.children]
        if self.operation == 'not':
            # An exclusion can allow a match without making it more specific.
            return (-1,) if scores[0] is None else None
        if self.operation == 'and' and any(score is None for score in scores):
            return None
        return max((score for score in scores if score is not None), default=None)


_TOKEN = re.compile(r'\s+|[LR]:|[\w*][\w.*-]*|[,|&()\->]', re.ASCII)
_NAME = re.compile(r'(?:[\w-]+|\*)(?:\.(?:[\w-]+|\*))*', re.ASCII)


class _Parser:
    def __init__(self, source: str) -> None:
        self.tokens = []
        self.position = 0
        self.depth = 0
        offset = 0
        while offset < len(source):
            match = _TOKEN.match(source, offset)
            if match is None:
                raise ThemeError(f'invalid selector character at offset {offset}')
            token = match.group()
            if not token.isspace():
                self.tokens.append(token)
            offset = match.end()
        if len(self.tokens) > 1024:
            raise ThemeError('selector has too many tokens')

    def peek(self) -> str:
        return self.tokens[self.position] if self.position < len(self.tokens) else ''

    def take(self) -> str:
        token = self.peek()
        self.position += 1
        return token

    def expression(self, *, nested: bool = False) -> Selector:
        children = [self.conjunction()]
        while self.peek() == '|' or (nested and self.peek() == ','):
            self.take()
            children.append(self.conjunction())
        return children[0] if len(children) == 1 else Selector('or', tuple(children))

    def conjunction(self) -> Selector:
        children = [self.operand()]
        while self.peek() and self.peek() not in {',', '|', ')'}:
            if self.peek() == '&':
                self.take()
            children.append(self.operand())
        return children[0] if len(children) == 1 else Selector('and', tuple(children))

    def operand(self) -> Selector:
        self.depth += 1
        if self.depth > 64:
            raise ThemeError('selector nesting exceeds 64 levels')
        try:
            token = self.take()
            if token == '-':
                return Selector('not', (self.operand(),))
            if token == '(':
                expression = self.expression(nested=True)
                if self.take() != ')':
                    raise ThemeError('selector is missing a closing parenthesis')
                return expression
            if token in {'', '-', '>', '&', '|', ',', ')', 'L:', 'R:'} or not _NAME.fullmatch(
                token
            ):
                raise ThemeError(f'expected a scope in selector, got {token!r}')
            path = [(token, False)]
            while self.peek():
                token = self.peek()
                direct = token == '>'
                if direct:
                    self.take()
                    token = self.peek()
                if token == '-' or not _NAME.fullmatch(token):
                    if direct:
                        raise ThemeError('child selector needs a scope after >')
                    break
                path.append((self.take(), direct))
            return Selector('path', path=tuple(path))
        finally:
            self.depth -= 1


@lru_cache(maxsize=1024)
def parse_selector(source: str, *, injection: bool = False) -> tuple[tuple[int, Selector], ...]:
    if not isinstance(source, str) or not source or source != source.strip():
        raise ThemeError('selectors must be nonempty strings without outer whitespace')
    if len(source) > 8192:
        raise ThemeError('selector exceeds 8192 characters')
    parser = _Parser(source)
    branches = []
    while True:
        priority = 0
        if injection and parser.peek() in {'L:', 'R:'}:
            priority = -1 if parser.take() == 'L:' else 1
        branches.append((priority, parser.expression()))
        if not parser.peek():
            break
        if parser.take() != ',':
            raise ThemeError('unexpected token in selector')
    return tuple(branches)


def selector_score(selector: str, scopes: tuple[str, ...]) -> Optional[tuple[int, ...]]:
    scores = (expression.score(scopes) for _, expression in parse_selector(selector))
    return max((score for score in scores if score is not None), default=None)
