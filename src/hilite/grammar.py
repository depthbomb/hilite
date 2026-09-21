import re
import plistlib
from typing import Any
from os import PathLike
from pathlib import Path
from typing import Optional
from types import MappingProxyType
from hilite._json import loads_jsonc
from hilite._oniguruma import Pattern
from dataclasses import field, dataclass
from hilite.models import ResourceLimits
from xml.parsers.expat import ExpatError
from hilite._engine import compile_pattern
from hilite.errors import ResourceLimitError
from hilite._selectors import Selector, parse_selector
from hilite.errors import ThemeError, GrammarError, MissingGrammarError
from collections.abc import Mapping, Callable, Iterable, Iterator, Sequence


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise GrammarError(f'{context} must be an object')
    return value


def _sequence(value: object, context: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GrammarError(f'{context} must be a sequence')
    return value


def _string_sequence(value: object, context: str) -> tuple[str, ...]:
    items = []
    for item in _sequence(value, context):
        if not isinstance(item, str):
            raise GrammarError(f'{context} must contain strings')
        items.append(item)
    return tuple(items)


def _freeze(value: Any, depth: int = 0) -> Any:
    if depth > 128:
        raise GrammarError('grammar data exceeds 128 nesting levels or contains a cycle')
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item, depth + 1) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_freeze(item, depth + 1) for item in value)
    return value


def load_data(path: str | PathLike[str]) -> Mapping[str, object]:
    file_path = Path(path)
    try:
        if file_path.suffix.lower() in {'.plist', '.tmlanguage', '.tmtheme'}:
            with file_path.open('rb') as stream:
                data = plistlib.load(stream)
        else:
            with file_path.open(encoding='utf-8-sig') as stream:
                data = loads_jsonc(stream.read())
    except (OSError, ValueError, ExpatError, plistlib.InvalidFileException) as error:
        raise GrammarError(f'could not load grammar {file_path}: {error}') from error
    return _mapping(data, f'grammar {file_path}')


@dataclass(frozen=True, slots=True)
class Grammar:
    scope_name: str
    language: str
    aliases: tuple[str, ...]
    raw: Mapping[str, object]
    source_path: Path | None = None
    inject_to: tuple[str, ...] = ()
    injection_selector: str | None = None

    def __post_init__(self) -> None:
        for label, value in (('scopeName', self.scope_name), ('language', self.language)):
            if not isinstance(value, str) or not value.strip():
                raise GrammarError(f'grammar {label} must be a nonempty string')
        aliases = tuple(self.aliases)
        targets = tuple(self.inject_to)
        if any(not isinstance(value, str) or not value.strip() for value in (*aliases, *targets)):
            raise GrammarError('grammar aliases and injection targets must be nonempty strings')
        object.__setattr__(self, 'aliases', tuple(dict.fromkeys((self.language, *aliases))))
        object.__setattr__(self, 'inject_to', targets)
        object.__setattr__(self, 'raw', _freeze(_mapping(self.raw, 'grammar')))

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, object],
        *,
        language: str | None = None,
        aliases: Iterable[str] = (),
        source_path: str | PathLike[str] | None = None,
        inject_to: Iterable[str] = (),
        injection_selector: str | None = None,
    ) -> Grammar:
        scope_name = data.get('scopeName')
        if not isinstance(scope_name, str) or not scope_name:
            raise GrammarError('grammar scopeName must be a nonempty string')
        selected_language = language or scope_name
        if not selected_language:
            raise GrammarError('grammar language must be a nonempty string')
        normalized_aliases = tuple(dict.fromkeys((selected_language, *aliases)))
        path = Path(source_path).resolve() if source_path is not None else None
        return cls(
            scope_name=scope_name,
            language=selected_language,
            aliases=normalized_aliases,
            raw=data,
            source_path=path,
            inject_to=tuple(inject_to),
            injection_selector=injection_selector,
        )

    @classmethod
    def from_file(
        cls,
        path: str | PathLike[str],
        *,
        language: str | None = None,
        aliases: Iterable[str] = (),
        inject_to: Iterable[str] = (),
        injection_selector: str | None = None,
    ) -> Grammar:
        return cls.from_dict(
            load_data(path),
            language=language,
            aliases=aliases,
            source_path=path,
            inject_to=inject_to,
            injection_selector=injection_selector,
        )


class GrammarRegistry:
    def __init__(self) -> None:
        self._revision = 0
        self._by_scope: dict[str, Grammar] = {}
        self._by_language: dict[str, Grammar] = {}
        self._injections: dict[str, list[Grammar]] = {}

    @property
    def revision(self) -> int:
        return self._revision

    def register(self, grammar: Grammar, *, replace: bool = False) -> None:
        existing = self._by_scope.get(grammar.scope_name)
        if existing is not None and existing is not grammar and not replace:
            raise GrammarError(f'duplicate grammar scope: {grammar.scope_name}')
        keys = tuple(alias.casefold() for alias in grammar.aliases)
        conflicts = [
            key
            for key in keys
            if key in self._by_language and self._by_language[key] is not existing
        ]
        if conflicts:
            raise GrammarError(f'duplicate grammar aliases: {", ".join(sorted(conflicts))}')
        if existing is not None and existing is not grammar:
            for key, value in tuple(self._by_language.items()):
                if value is existing:
                    del self._by_language[key]
            for target, grammars in tuple(self._injections.items()):
                remaining = [item for item in grammars if item is not existing]
                if remaining:
                    self._injections[target] = remaining
                else:
                    del self._injections[target]
        self._by_scope[grammar.scope_name] = grammar
        for key in keys:
            self._by_language[key] = grammar
        for target in grammar.inject_to:
            bucket = self._injections.setdefault(target, [])
            bucket[:] = [item for item in bucket if item.scope_name != grammar.scope_name]
            bucket.append(grammar)
        self._revision += 1

    def register_dict(
        self,
        data: Mapping[str, object],
        *,
        language: str | None = None,
        aliases: Iterable[str] = (),
        inject_to: Iterable[str] = (),
        injection_selector: str | None = None,
        replace: bool = False,
    ) -> Grammar:
        grammar = Grammar.from_dict(
            data,
            language=language,
            aliases=aliases,
            inject_to=inject_to,
            injection_selector=injection_selector,
        )
        self.register(grammar, replace=replace)
        return grammar

    def register_file(
        self,
        path: str | PathLike[str],
        *,
        language: str | None = None,
        aliases: Iterable[str] = (),
        inject_to: Iterable[str] = (),
        injection_selector: str | None = None,
        replace: bool = False,
    ) -> Grammar:
        grammar = Grammar.from_file(
            path,
            language=language,
            aliases=aliases,
            inject_to=inject_to,
            injection_selector=injection_selector,
        )
        self.register(grammar, replace=replace)
        return grammar

    def unregister(self, language_or_scope: str) -> None:
        grammar = self.get(language_or_scope)
        self._by_scope.pop(grammar.scope_name, None)
        for key, value in tuple(self._by_language.items()):
            if value is grammar:
                del self._by_language[key]
        for target, grammars in tuple(self._injections.items()):
            remaining = [item for item in grammars if item is not grammar]
            if remaining:
                self._injections[target] = remaining
            else:
                del self._injections[target]
        self._revision += 1

    def get(self, language_or_scope: str) -> Grammar:
        grammar = self._by_scope.get(language_or_scope)
        if grammar is None:
            grammar = self._by_language.get(language_or_scope.casefold())
        if grammar is None:
            available = ', '.join(sorted(self.languages)) or 'none'
            raise MissingGrammarError(
                f'no grammar registered for {language_or_scope!r}; available languages: {available}'
            )
        return grammar

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(sorted({grammar.language for grammar in self._by_scope.values()}))

    def injections_for(self, scope_name: str) -> tuple[Grammar, ...]:
        return tuple(self._injections.get(scope_name, ()))

    def import_extension(
        self,
        directory: str | PathLike[str],
        *,
        replace: bool = False,
    ) -> tuple[Grammar, ...]:
        root = Path(directory).resolve()
        manifest_path = root / 'package.json'
        try:
            with manifest_path.open(encoding='utf-8-sig') as stream:
                manifest = loads_jsonc(stream.read())
        except (OSError, ValueError) as error:
            raise GrammarError(
                f'could not load extension manifest {manifest_path}: {error}'
            ) from error
        manifest = _mapping(manifest, f'extension manifest {manifest_path}')
        contributes = _mapping(manifest.get('contributes', {}), 'manifest contributes')
        languages = contributes.get('languages', ())
        language_aliases: dict[str, tuple[str, ...]] = {}
        for entry in _sequence(languages, 'contributes.languages'):
            item = _mapping(entry, 'language contribution')
            language_id = item.get('id')
            if not isinstance(language_id, str):
                raise GrammarError('language contribution id must be a string')
            aliases = item.get('aliases', ())
            alias_values = _string_sequence(aliases, f'aliases for {language_id}')
            language_aliases[language_id] = alias_values

        # Only update the real registry after every file in the extension checks out.
        staged = GrammarRegistry()
        staged._by_scope = dict(self._by_scope)
        staged._by_language = dict(self._by_language)
        staged._injections = {target: list(items) for target, items in self._injections.items()}
        registered = []
        grammars = _sequence(contributes.get('grammars', ()), 'contributes.grammars')
        for entry in grammars:
            item = _mapping(entry, 'grammar contribution')
            relative_path = item.get('path')
            scope_name = item.get('scopeName')
            language = item.get('language')
            if not isinstance(relative_path, str) or not isinstance(scope_name, str):
                raise GrammarError('grammar contributions need string path and scopeName values')
            if language is not None and not isinstance(language, str):
                raise GrammarError('grammar contribution language must be a string')
            grammar_path = (root / relative_path).resolve()
            if root not in grammar_path.parents:
                raise GrammarError(f'grammar path escapes the extension directory: {relative_path}')
            inject_to = item.get('injectTo', ())
            injection_targets = _string_sequence(inject_to, f'injectTo for {scope_name}')
            injection_selector = item.get('injectionSelector')
            grammar = Grammar.from_file(
                grammar_path,
                language=language or scope_name,
                aliases=language_aliases.get(language or '', ()),
                inject_to=injection_targets,
                injection_selector=injection_selector
                if isinstance(injection_selector, str)
                else None,
            )
            if grammar.scope_name != scope_name:
                message = (
                    f'{grammar_path} declares {grammar.scope_name!r}, '
                    f'manifest expects {scope_name!r}'
                )
                raise GrammarError(message)
            staged.register(grammar, replace=replace)
            registered.append(grammar)
        self._by_scope = staged._by_scope
        self._by_language = staged._by_language
        self._injections = staged._injections
        self._revision += 1
        return tuple(registered)


@dataclass(frozen=True, slots=True)
class Capture:
    group: int
    name: Optional[str]
    content_name: Optional[str]
    patterns: Optional[tuple[CompiledRule, ...]]
    owner_scope: str
    path: str


@dataclass(frozen=True, slots=True)
class MatchRule:
    regex: Pattern
    name: str | None
    captures: tuple[Capture, ...]
    owner_scope: str
    path: str


@dataclass(frozen=True, slots=True)
class BeginRule:
    begin: Pattern
    end_source: str | None
    end: Optional[Pattern]
    while_source: str | None
    while_regex: Optional[Pattern]
    name: str | None
    content_name: str | None
    begin_captures: tuple[Capture, ...]
    end_captures: tuple[Capture, ...]
    while_captures: tuple[Capture, ...]
    patterns: tuple[CompiledRule, ...]
    apply_end_last: bool
    owner_scope: str
    path: str


@dataclass(frozen=True, slots=True)
class IncludeRule:
    include: str
    owner_scope: str
    path: str
    repository: Mapping[str, CompiledRule] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ContainerRule:
    patterns: tuple[CompiledRule, ...]
    path: str


CompiledRule = MatchRule | BeginRule | IncludeRule | ContainerRule


@dataclass(frozen=True, slots=True)
class _Repository(Mapping[str, CompiledRule]):
    local: Mapping[str, CompiledRule]
    parent: Mapping[str, CompiledRule]

    def __getitem__(self, name: str) -> CompiledRule:
        try:
            return self.local[name]
        except KeyError:
            return self.parent[name]

    def __iter__(self) -> Iterator[str]:
        yield from self.local
        for name in self.parent:
            if name not in self.local:
                yield name

    def __len__(self) -> int:
        return sum(1 for _ in self)


@dataclass(frozen=True, slots=True)
class PreparedGrammar:
    grammar: Grammar
    patterns: tuple[CompiledRule, ...]
    repository: Mapping[str, CompiledRule]
    injections: tuple[tuple[str, tuple[CompiledRule, ...]], ...]


class GrammarCompiler:
    def __init__(self, limits: Optional[ResourceLimits] = None) -> None:
        self._limits = limits or ResourceLimits()
        self._rule_count = 0

    def compile(self, grammar: Grammar) -> PreparedGrammar:
        selector = grammar.injection_selector or grammar.raw.get('injectionSelector')
        if selector is not None:
            if not isinstance(selector, str):
                raise GrammarError(f'{grammar.scope_name} injection selector must be a string')
            _injection_alternatives(selector)
        repository = self._repository(grammar, grammar.raw.get('repository', {}), 'repository', {})
        patterns = self._compile_patterns(
            grammar, grammar.raw.get('patterns', ()), 'patterns', repository
        )
        injection_data = _mapping(
            grammar.raw.get('injections', {}), f'{grammar.scope_name} injections'
        )
        injections = []
        for selector, value in injection_data.items():
            if not isinstance(selector, str):
                raise GrammarError(f'{grammar.scope_name} injection selectors must be strings')
            _injection_alternatives(selector)
            rule = self._compile_rule(
                grammar,
                _mapping(value, f'injection {selector}'),
                f'injections[{selector!r}]',
                repository,
            )
            injections.append((selector, (rule,)))
        return PreparedGrammar(grammar, patterns, repository, tuple(injections))

    def _repository(
        self,
        grammar: Grammar,
        value: object,
        path: str,
        parent: Mapping[str, CompiledRule],
    ) -> Mapping[str, CompiledRule]:
        local: dict[str, CompiledRule] = {}
        # Keep this layer live while we fill it in, so sibling rules can include each other.
        repository = MappingProxyType(_Repository(local, parent))
        for name, raw in _mapping(value, path).items():
            if not isinstance(name, str) or not name:
                raise GrammarError(f'{grammar.scope_name} {path}: repository names must be strings')
            local[name] = self._compile_rule(
                grammar, _mapping(raw, f'{path}[{name!r}]'), f'{path}[{name!r}]', repository
            )
        return repository

    def _compile_patterns(
        self,
        grammar: Grammar,
        value: object,
        path: str,
        repository: Mapping[str, CompiledRule],
    ) -> tuple[CompiledRule, ...]:
        return tuple(
            self._compile_rule(
                grammar, _mapping(rule, f'{path}[{index}]'), f'{path}[{index}]', repository
            )
            for index, rule in enumerate(_sequence(value, path))
        )

    def _captures(
        self,
        grammar: Grammar,
        value: object,
        path: str,
        repository: Mapping[str, CompiledRule],
    ) -> tuple[Capture, ...]:
        if value is None:
            return ()
        captures = []
        for group, raw in _mapping(value, path).items():
            try:
                number = int(group)
            except (TypeError, ValueError) as error:
                raise GrammarError(
                    f'{grammar.scope_name} {path}: capture keys must be integers'
                ) from error
            item = _mapping(raw, f'{path}.{group}')
            name = item.get('name')
            if name is not None and not isinstance(name, str):
                raise GrammarError(f'{grammar.scope_name} {path}.{group}.name must be a string')
            content_name = item.get('contentName')
            if content_name is not None and not isinstance(content_name, str):
                raise GrammarError(
                    f'{grammar.scope_name} {path}.{group}.contentName must be a string'
                )
            patterns = None
            if 'patterns' in item:
                compiled = self._compile_rule(grammar, item, f'{path}.{group}', repository)
                if not isinstance(compiled, ContainerRule):
                    raise GrammarError(
                        f'{grammar.scope_name} {path}.{group}: expected capture patterns'
                    )
                patterns = compiled.patterns
            captures.append(
                Capture(number, name, content_name, patterns, grammar.scope_name, f'{path}.{group}')
            )
            if number < 0:
                raise GrammarError(f'{grammar.scope_name} {path}: capture keys must be nonnegative')
        return tuple(sorted(captures, key=lambda capture: capture.group))

    def _compile_rule(
        self,
        grammar: Grammar,
        raw: Mapping[str, object],
        path: str,
        repository: Mapping[str, CompiledRule],
    ) -> CompiledRule:
        self._rule_count += 1
        if self._rule_count > self._limits.max_grammar_rules:
            raise ResourceLimitError(f'{grammar.scope_name}: grammar rule count limit exceeded')
        if raw.get('disabled'):
            return ContainerRule((), path)
        for pattern_field in ('match', 'begin', 'end', 'while'):
            pattern = raw.get(pattern_field)
            if isinstance(pattern, str) and len(pattern) > self._limits.max_pattern_chars:
                raise ResourceLimitError(
                    f'{grammar.scope_name} {path}.{pattern_field}: pattern is too long'
                )
        if 'repository' in raw:
            repository = self._repository(
                grammar, raw['repository'], f'{path}.repository', repository
            )
        include = raw.get('include')
        if include is not None:
            if not isinstance(include, str) or not include:
                raise GrammarError(f'{grammar.scope_name} {path}.include must be a nonempty string')
            return IncludeRule(include, grammar.scope_name, path, repository)

        match = raw.get('match')
        if match is not None:
            if not isinstance(match, str):
                raise GrammarError(f'{grammar.scope_name} {path}.match must be a string')
            name = raw.get('name')
            if name is not None and not isinstance(name, str):
                raise GrammarError(f'{grammar.scope_name} {path}.name must be a string')
            regex = compile_pattern(match, grammar=grammar.scope_name, rule_path=f'{path}.match')
            captures = self._captures(grammar, raw.get('captures'), f'{path}.captures', repository)
            return MatchRule(regex, name, captures, grammar.scope_name, path)

        begin = raw.get('begin')
        if begin is not None:
            if not isinstance(begin, str):
                raise GrammarError(f'{grammar.scope_name} {path}.begin must be a string')
            end_source = raw.get('end')
            while_source = raw.get('while')
            if (end_source is None) == (while_source is None):
                raise GrammarError(f'{grammar.scope_name} {path} needs exactly one of end or while')
            if end_source is not None and not isinstance(end_source, str):
                raise GrammarError(f'{grammar.scope_name} {path}.end must be a string')
            if while_source is not None and not isinstance(while_source, str):
                raise GrammarError(f'{grammar.scope_name} {path}.while must be a string')
            name = raw.get('name')
            content_name = raw.get('contentName')
            if name is not None and not isinstance(name, str):
                raise GrammarError(f'{grammar.scope_name} {path}.name must be a string')
            if content_name is not None and not isinstance(content_name, str):
                raise GrammarError(f'{grammar.scope_name} {path}.contentName must be a string')
            end = None
            # The begin match supplies these backreferences later. Check the rest now.
            if end_source is not None and _has_backreference(end_source):
                compile_pattern(
                    _BACKREFERENCE.sub(lambda m: '(?:)' if m.group(1) else m.group(), end_source),
                    grammar=grammar.scope_name,
                    rule_path=f'{path}.end',
                )
            if end_source is not None and not _has_backreference(end_source):
                end = compile_pattern(
                    end_source,
                    grammar=grammar.scope_name,
                    rule_path=f'{path}.end',
                )
            while_regex = None
            if while_source is not None and _has_backreference(while_source):
                compile_pattern(
                    _BACKREFERENCE.sub(lambda m: '(?:)' if m.group(1) else m.group(), while_source),
                    grammar=grammar.scope_name,
                    rule_path=f'{path}.while',
                )
            if while_source is not None and not _has_backreference(while_source):
                while_regex = compile_pattern(
                    while_source,
                    grammar=grammar.scope_name,
                    rule_path=f'{path}.while',
                )
            raw_captures = raw.get('captures')
            begin_captures = self._captures(
                grammar,
                raw.get('beginCaptures', raw_captures),
                f'{path}.beginCaptures',
                repository,
            )
            end_captures = self._captures(
                grammar,
                raw.get('endCaptures', raw_captures),
                f'{path}.endCaptures',
                repository,
            )
            while_captures = self._captures(
                grammar,
                raw.get('whileCaptures', raw_captures),
                f'{path}.whileCaptures',
                repository,
            )
            patterns = self._compile_patterns(
                grammar, raw.get('patterns', ()), f'{path}.patterns', repository
            )
            return BeginRule(
                begin=compile_pattern(
                    begin,
                    grammar=grammar.scope_name,
                    rule_path=f'{path}.begin',
                ),
                end_source=end_source,
                end=end,
                while_source=while_source,
                while_regex=while_regex,
                name=name,
                content_name=content_name,
                begin_captures=begin_captures,
                end_captures=end_captures,
                while_captures=while_captures,
                patterns=patterns,
                apply_end_last=bool(raw.get('applyEndPatternLast', False)),
                owner_scope=grammar.scope_name,
                path=path,
            )

        raw_patterns = raw.get('patterns')
        if raw_patterns is not None:
            return ContainerRule(
                self._compile_patterns(grammar, raw_patterns, f'{path}.patterns', repository), path
            )
        raise GrammarError(f'{grammar.scope_name} {path} has no match, begin, include, or patterns')


def _has_backreference(pattern: str) -> bool:
    return any(match.group(1) is not None for match in _BACKREFERENCE.finditer(pattern))


def substitute_backreferences(
    pattern: str,
    groups: tuple[Optional[str], ...],
    *,
    max_chars: Optional[int] = None,
) -> str:
    size = len(pattern)

    def replace(match: re.Match[str]) -> str:
        nonlocal size
        reference = match.group(1)
        if reference is None:
            return match.group()
        number = int(reference)
        if number > len(groups):
            raise GrammarError(f'end/while backreference {number} exceeds the begin capture count')
        # Captured delimiters are literal text, even if they contain regex punctuation.
        replacement = re.escape(groups[number - 1] or '')
        size += len(replacement) - len(match.group())
        if max_chars is not None and size > max_chars:
            raise ResourceLimitError('expanded end/while pattern exceeds max_pattern_chars')
        return replacement

    return _BACKREFERENCE.sub(replace, pattern)


_BACKREFERENCE = re.compile(r'\\\\|\\([1-9][0-9]*)')


def injection_selector_priority(selector: str, scopes: tuple[str, ...]) -> Optional[int]:
    return min(
        (
            priority
            for priority, expression in _injection_alternatives(selector)
            if expression.score(scopes) is not None
        ),
        default=None,
    )


def injection_selector_matches(selector: str, scopes: tuple[str, ...]) -> tuple[bool, bool]:
    priority = injection_selector_priority(selector, scopes)
    return priority is not None, priority == -1


def _injection_alternatives(selector: str) -> tuple[tuple[int, Selector], ...]:
    try:
        return parse_selector(selector, injection=True)
    except ThemeError as error:
        raise GrammarError(f'invalid injection selector {selector!r}: {error}') from error


PreparedLookup = Callable[[str], PreparedGrammar]
