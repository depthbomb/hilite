import re
import time
from typing import Any
from threading import RLock
from typing import Optional
from itertools import pairwise
from collections import OrderedDict
from hilite._engine import compile_pattern
from collections.abc import Iterable, Iterator
from dataclasses import field, replace, dataclass
from hilite._oniguruma import Line, Match, Pattern, Scanner
from hilite.models import TokenSpan, TokenizedCode, ResourceLimits
from hilite.errors import GrammarError, ResourceLimitError, MissingGrammarError
from hilite.grammar import (
    Capture,
    BeginRule,
    MatchRule,
    CompiledRule,
    ContainerRule,
    PreparedLookup,
    PreparedGrammar,
    substitute_backreferences,
    injection_selector_priority,
)


type _RuleScan = tuple[tuple[MatchRule | BeginRule, ...], int, int, Scanner]
type _RuleCache = dict[tuple[str, str, tuple[str, ...]], _RuleScan]


@dataclass(slots=True)
class Frame:
    rule: BeginRule
    owner_scope: str
    begin_scopes: tuple[str, ...]
    content_scopes: tuple[str, ...]
    end_regex: Optional[Pattern]
    while_regex: Optional[Pattern]
    anchor_position: int
    begin_captured_eol: bool


@dataclass(frozen=True, slots=True)
class Candidate:
    start: int
    end: int
    order: float
    rule: MatchRule | BeginRule | None
    match: Match
    is_end: bool = False


@dataclass(slots=True)
class LineContext:
    text: str
    offset: int
    root: PreparedGrammar
    deadline: Optional[float]
    rule_cache: _RuleCache
    active_captures: set[tuple[str, str, int, int]] = field(default_factory=set)


class Tokenizer:
    def __init__(
        self,
        prepared_lookup: PreparedLookup,
        injection_lookup: Any,
        limits: ResourceLimits,
    ) -> None:
        self._prepared_lookup = prepared_lookup
        self._injection_lookup = injection_lookup
        self._limits = limits
        self._dynamic_patterns: OrderedDict[tuple[str, str], Pattern] = OrderedDict()
        self._cache_lock = RLock()

    def clear(self) -> None:
        with self._cache_lock:
            self._dynamic_patterns.clear()

    @property
    def dynamic_pattern_count(self) -> int:
        with self._cache_lock:
            return len(self._dynamic_patterns)

    def validate(self, prepared: PreparedGrammar) -> None:
        seen: set[tuple[str, str]] = set()
        pending = [prepared.patterns, *(patterns for _, patterns in prepared.injections)]
        for grammar in self._injection_lookup(prepared.grammar.scope_name):
            pending.append(self._prepared_lookup(grammar.scope_name).patterns)
        while pending:
            for rule in self._expanded_rules(pending.pop(), prepared):
                key = (rule.owner_scope, rule.path)
                if key in seen:
                    continue
                seen.add(key)
                if isinstance(rule, BeginRule):
                    pending.append(rule.patterns)
                    captures = (*rule.begin_captures, *rule.end_captures, *rule.while_captures)
                else:
                    captures = rule.captures
                for capture in captures:
                    if capture.patterns is not None:
                        pending.append(capture.patterns)

    def tokenize(
        self,
        source: str,
        prepared: PreparedGrammar,
        *,
        deadline: Optional[float] = None,
    ) -> TokenizedCode:
        if len(source) > self._limits.max_input_chars:
            raise ResourceLimitError(
                f'input contains {len(source)} characters; limit is {self._limits.max_input_chars}'
            )
        if deadline is None and self._limits.timeout_seconds is not None:
            deadline = time.monotonic() + self._limits.timeout_seconds
        root_scopes = (prepared.grammar.scope_name,)
        rule_cache: _RuleCache = {}
        stack: list[Frame] = []
        spans: list[TokenSpan] = []
        for line_number, (line_start, content_end, physical_end) in enumerate(
            _physical_lines(source),
            start=1,
        ):
            text = source[line_start:content_end]
            if len(text) > self._limits.max_line_chars:
                raise ResourceLimitError(
                    f'line {line_number} contains {len(text)} characters; '
                    f'limit is {self._limits.max_line_chars}'
                )
            # TextMate scans every line with a trailing newline, even the last one.
            text += '\n'
            line_spans: list[TokenSpan] = []
            native_line = Line(text)
            context = LineContext(text, line_start, prepared, deadline, rule_cache)
            position, anchor_position = self._check_while_rules(
                context, stack, line_spans, native_line
            )
            self._tokenize_line(
                context, position, root_scopes, stack, line_spans, anchor_position, native_line
            )
            if line_spans:
                last = line_spans[-1]
                # Map that extra newline back to the real CRLF, LF, or end of file.
                if last.end != physical_end:
                    if last.start >= physical_end:
                        line_spans.pop()
                    else:
                        line_spans[-1] = TokenSpan(last.start, physical_end, last.scopes)
            if line_spans:
                first = line_spans[0]
                self._emit(spans, first.start, first.end, first.scopes)
                spans.extend(line_spans[1:])
                if len(spans) > self._limits.max_spans:
                    raise ResourceLimitError(f'token span count exceeded {self._limits.max_spans}')
        self._check_deadline(deadline)
        return TokenizedCode(
            source=source,
            language=prepared.grammar.language,
            root_scope=prepared.grammar.scope_name,
            spans=tuple(spans),
        )

    def _check_while_rules(
        self,
        context: LineContext,
        stack: list[Frame],
        spans: list[TokenSpan],
        native_line: Line,
    ) -> tuple[int, int]:
        line_start = context.offset
        deadline = context.deadline
        position = 0
        anchor_position = 0 if stack and stack[-1].begin_captured_eol else -1
        index = 0
        while index < len(stack):
            frame = stack[index]
            if frame.while_regex is None:
                index += 1
                continue
            match = self._search(
                frame.while_regex,
                position,
                deadline,
                line_start == 0,
                anchor_position,
                native_line=native_line,
            )
            if match is None:
                # Once a parent stops continuing, everything nested inside it ends too.
                del stack[index:]
                break
            base_scopes = frame.content_scopes
            self._emit(spans, line_start + position, line_start + match.start(), base_scopes)
            self._emit_captures(
                context,
                spans,
                match,
                base_scopes,
                None,
                frame.rule.while_captures,
                index + 1,
            )
            position = match.end()
            anchor_position = position
            index += 1
        return position, anchor_position

    def _tokenize_line(
        self,
        context: LineContext,
        position: int,
        root_scopes: tuple[str, ...],
        stack: list[Frame],
        spans: list[TokenSpan],
        anchor_position: int,
        native_line: Line,
        capture: Optional[Capture] = None,
        nesting: int = 0,
    ) -> None:
        text = context.text
        line_start = context.offset
        root = context.root
        deadline = context.deadline
        rule_cache = context.rule_cache
        base_patterns = root.patterns if capture is None else capture.patterns
        if base_patterns is None:
            raise GrammarError('capture retokenization requires patterns')
        seen: set[tuple[tuple[str, str], ...]] = set()
        previous_position = -1
        while position < len(text):
            self._check_deadline(deadline)
            current_scopes = stack[-1].content_scopes if stack else root_scopes
            owner_scope = (
                stack[-1].owner_scope
                if stack
                else (capture.owner_scope if capture is not None else root.grammar.scope_name)
            )
            patterns = stack[-1].rule.patterns if stack else base_patterns
            path = (
                stack[-1].rule.path if stack else (capture.path if capture is not None else '$root')
            )
            # The same rule can pick up different injections under different scopes.
            cache_key = (path, owner_scope, current_scopes)
            cached = rule_cache.get(cache_key)
            if cached is None:
                rules = tuple(self._expanded_rules(patterns, root))
                left, right = self._injection_rules(root, current_scopes)
                ordered = (*left, *rules, *right)
                scanner = Scanner(
                    [rule.regex if isinstance(rule, MatchRule) else rule.begin for rule in ordered]
                )
                cached = (ordered, len(left), len(rules), scanner)
                if len(rule_cache) < 2048:
                    rule_cache[cache_key] = cached
            ordered_rules, left_count, rule_count, scanner = cached
            candidate = self._pattern_candidate(
                ordered_rules,
                position,
                deadline,
                line_start == 0,
                anchor_position,
                scanner,
                native_line,
            )
            # Half steps put the end rule between entries without reordering the scanner.
            end_order = left_count - 0.5
            if stack and stack[-1].rule.apply_end_last:
                end_order += rule_count
            end_candidate = self._end_candidate(
                stack,
                position,
                deadline,
                line_start == 0,
                anchor_position,
                native_line,
                end_order,
            )
            if end_candidate is not None and (
                candidate is None
                or (end_candidate.start, end_candidate.order) < (candidate.start, candidate.order)
            ):
                candidate = end_candidate
            if candidate is None:
                self._emit(spans, line_start + position, line_start + len(text), current_scopes)
                return
            # Empty matches are fine for state changes, as long as they don't loop.
            if candidate.start == candidate.end:
                if candidate.start != previous_position:
                    seen.clear()
                    previous_position = candidate.start
                state = tuple((frame.owner_scope, frame.rule.path) for frame in stack)
                if state in seen:
                    raise GrammarError(
                        f'{root.grammar.scope_name}: zero-width grammar transitions made no '
                        f'progress at offset {line_start + candidate.start}'
                    )
                seen.add(state)
            if candidate.start > position:
                self._emit(
                    spans,
                    line_start + position,
                    line_start + candidate.start,
                    current_scopes,
                )
            position = candidate.start
            if candidate.is_end:
                frame = stack.pop()
                anchor_position = frame.anchor_position
                self._emit_captures(
                    context,
                    spans,
                    candidate.match,
                    frame.begin_scopes,
                    None,
                    frame.rule.end_captures,
                    nesting + len(stack) + 1,
                )
                position = candidate.end
                continue
            rule = candidate.rule
            if isinstance(rule, MatchRule):
                if rule.captures:
                    self._emit_captures(
                        context,
                        spans,
                        candidate.match,
                        current_scopes,
                        rule.name,
                        rule.captures,
                        nesting + len(stack) + 1,
                    )
                else:
                    self._emit(
                        spans,
                        line_start + candidate.start,
                        line_start + candidate.end,
                        current_scopes + _scope_names(rule.name, candidate.match),
                    )
                if candidate.end == candidate.start:
                    raise GrammarError(
                        f'{root.grammar.scope_name} {rule.path}: zero-width match rule '
                        f'made no state change at offset {line_start + position}'
                    )
                position = candidate.end
                continue
            if isinstance(rule, BeginRule):
                begin_scopes = current_scopes + _scope_names(rule.name, candidate.match)
                self._emit_captures(
                    context,
                    spans,
                    candidate.match,
                    begin_scopes,
                    None,
                    rule.begin_captures,
                    nesting + len(stack) + 1,
                )
                if nesting + len(stack) >= self._limits.max_nesting:
                    raise ResourceLimitError(
                        f'grammar nesting exceeded {self._limits.max_nesting} levels'
                    )
                owner_scope = rule.owner_scope
                end_regex = self._frame_regex(
                    rule.end_source,
                    rule.end,
                    candidate.match,
                    owner_scope,
                    rule.path,
                )
                while_regex = self._frame_regex(
                    rule.while_source,
                    rule.while_regex,
                    candidate.match,
                    owner_scope,
                    rule.path,
                )
                content_scopes = begin_scopes + _scope_names(rule.content_name, candidate.match)
                stack.append(
                    Frame(
                        rule,
                        owner_scope,
                        begin_scopes,
                        content_scopes,
                        end_regex,
                        while_regex,
                        anchor_position,
                        candidate.end == len(text),
                    )
                )
                anchor_position = candidate.end
                position = candidate.end
                continue
            raise AssertionError('unreachable candidate rule')

    def _expanded_rules(
        self,
        rules: Iterable[CompiledRule],
        base: PreparedGrammar,
    ) -> Iterable[MatchRule | BeginRule]:
        # Keep our own stack so long include chains don't hit Python's recursion limit.
        visited: set[tuple[str, str]] = set()
        pending: list[tuple[Iterator[CompiledRule], Optional[tuple[str, str]]]] = [
            (iter(rules), None)
        ]
        while pending:
            iterator, parent_key = pending[-1]
            rule = next(iterator, None)
            if rule is None:
                pending.pop()
                if parent_key is not None:
                    # Block cycles in this branch, but allow reuse in a sibling branch.
                    visited.remove(parent_key)
                continue
            if isinstance(rule, (MatchRule, BeginRule)):
                yield rule
                continue
            if isinstance(rule, ContainerRule):
                pending.append((iter(rule.patterns), None))
                continue
            include_key = (rule.owner_scope, rule.path)
            if include_key in visited:
                continue
            targets: Iterable[CompiledRule]
            if rule.include.startswith('#'):
                name = rule.include[1:]
                target = rule.repository.get(name)
                if target is None:
                    raise GrammarError(
                        f'{rule.owner_scope} {rule.path}: missing repository rule {name!r}'
                    )
                targets = (target,)
            elif rule.include in {'$self', '$base'}:
                # $base stays with the original grammar, even inside an embedded one.
                target_owner = (
                    self._prepared_lookup(rule.owner_scope) if rule.include == '$self' else base
                )
                targets = target_owner.patterns
            else:
                scope, marker, repository_name = rule.include.partition('#')
                try:
                    external = self._prepared_lookup(scope)
                except MissingGrammarError as error:
                    raise GrammarError(
                        f'{rule.owner_scope} {rule.path}: missing external grammar {scope!r}'
                    ) from error
                if marker:
                    target = external.repository.get(repository_name)
                    if target is None:
                        raise GrammarError(
                            f'{rule.owner_scope} {rule.path}: {scope!r} has no repository '
                            f'rule {repository_name!r}'
                        )
                    targets = (target,)
                else:
                    targets = external.patterns
            visited.add(include_key)
            pending.append((iter(targets), include_key))

    def _injection_rules(
        self,
        root: PreparedGrammar,
        scopes: tuple[str, ...],
    ) -> tuple[tuple[MatchRule | BeginRule, ...], tuple[MatchRule | BeginRule, ...]]:
        left: list[MatchRule | BeginRule] = []
        right: list[MatchRule | BeginRule] = []
        sources = list(root.injections)
        for grammar in self._injection_lookup(root.grammar.scope_name):
            prepared = self._prepared_lookup(grammar.scope_name)
            selector = grammar.injection_selector or grammar.raw.get('injectionSelector')
            if not isinstance(selector, str):
                selector = root.grammar.scope_name
            sources.append((selector, prepared.patterns))
        matched = []
        for index, (selector, patterns) in enumerate(sources):
            priority = injection_selector_priority(selector, scopes)
            if priority is not None:
                matched.append((priority, index, patterns))
        for priority, _, patterns in sorted(matched, key=lambda item: item[:2]):
            expanded = self._expanded_rules(patterns, root)
            (left if priority == -1 else right).extend(expanded)
        return tuple(left), tuple(right)

    def _pattern_candidate(
        self,
        rules: tuple[MatchRule | BeginRule, ...],
        position: int,
        deadline: float | None,
        document_start: bool,
        anchor_position: int,
        scanner: Scanner,
        native_line: Line,
    ) -> Optional[Candidate]:
        timeout = None if deadline is None else deadline - time.monotonic()
        try:
            result = scanner.find(
                native_line,
                position,
                document_start and position == 0,
                position == anchor_position,
                timeout,
            )
        except TimeoutError as error:
            raise ResourceLimitError(str(error)) from error
        if result is None:
            return None
        order, match = result
        return Candidate(match.start(), match.end(), order, rules[order], match)

    def _end_candidate(
        self,
        stack: list[Frame],
        position: int,
        deadline: float | None,
        document_start: bool,
        anchor_position: int,
        native_line: Line,
        order: float,
    ) -> Candidate | None:
        regex = stack[-1].end_regex if stack else None
        if regex is None:
            return None
        match = self._search(
            regex,
            position,
            deadline,
            document_start,
            anchor_position,
            native_line,
        )
        if match is None:
            return None
        return Candidate(match.start(), match.end(), order, None, match, True)

    def _frame_regex(
        self,
        source: str | None,
        compiled: Optional[Pattern],
        begin_match: Match,
        grammar: str,
        path: str,
    ) -> Optional[Pattern]:
        if source is None:
            return None
        if compiled is not None:
            return compiled
        substituted = substitute_backreferences(
            source, begin_match.groups(), max_chars=self._limits.max_pattern_chars
        )
        key = (grammar, substituted)
        with self._cache_lock:
            cached = self._dynamic_patterns.get(key)
            if cached is not None:
                self._dynamic_patterns.move_to_end(key)
                return cached
        result = compile_pattern(
            substituted,
            grammar=grammar,
            rule_path=f'{path}.dynamic',
        )
        with self._cache_lock:
            self._dynamic_patterns[key] = result
            while len(self._dynamic_patterns) > self._limits.max_dynamic_patterns:
                self._dynamic_patterns.popitem(last=False)
        return result

    def _search(
        self,
        regex: Pattern,
        position: int,
        deadline: Optional[float],
        document_start: bool,
        anchor_position: int,
        native_line: Line,
    ) -> Optional[Match]:
        timeout = None if deadline is None else deadline - time.monotonic()
        try:
            return native_line.search(
                regex,
                position,
                document_start and position == 0,
                position == anchor_position,
                timeout,
            )
        except TimeoutError as error:
            raise ResourceLimitError(str(error)) from error

    def _check_deadline(self, deadline: float | None) -> None:
        if deadline is not None and time.monotonic() >= deadline:
            raise ResourceLimitError('highlighting exceeded its total deadline')

    def _emit_captures(
        self,
        context: LineContext,
        spans: list[TokenSpan],
        match: Match,
        base_scopes: tuple[str, ...],
        name: Optional[str],
        captures: tuple[Capture, ...],
        nesting: int,
    ) -> None:
        start, end = match.start(), match.end()
        scopes = base_scopes + _scope_names(name, match)
        if not captures:
            self._emit(spans, context.offset + start, context.offset + end, scopes)
            return
        intervals = []
        retokenized = []
        consumed = start
        for capture in captures:
            self._check_deadline(context.deadline)
            try:
                # Lookarounds can capture outside the text this match actually consumes.
                capture_start = max(start, match.start(capture.group))
                capture_end = min(end, match.end(capture.group))
            except IndexError as error:
                raise GrammarError(f'capture group {capture.group} does not exist') from error
            if capture_end <= capture_start or capture_end <= consumed:
                continue
            if capture.patterns is not None:
                if nesting >= self._limits.max_nesting:
                    raise ResourceLimitError(
                        'capture retokenization exceeded grammar nesting limit'
                    )
                key = (capture.owner_scope, capture.path, capture_start, capture_end)
                if key in context.active_captures:
                    raise GrammarError('capture retokenization made no progress')
                context.active_captures.add(key)
                nested_spans: list[TokenSpan] = []
                # Keep the line prefix so lookbehind and start-of-line anchors still work.
                nested_text = context.text[:capture_end]
                nested_scopes = (
                    scopes
                    + _scope_names(capture.name, match)
                    + _scope_names(capture.content_name, match)
                )
                try:
                    self._tokenize_line(
                        replace(context, text=nested_text),
                        capture_start,
                        nested_scopes,
                        [],
                        nested_spans,
                        -1,
                        Line(nested_text),
                        capture,
                        nesting,
                    )
                finally:
                    context.active_captures.remove(key)
                for span in nested_spans:
                    if span.end - context.offset <= consumed:
                        continue
                    retokenized.append(
                        (
                            max(consumed, span.start - context.offset),
                            span.end - context.offset,
                            span.scopes,
                        )
                    )
                # Later captures shouldn't paint over text we've already retokenized.
                consumed = max(consumed, capture_end)
            elif capture.name:
                intervals.append(
                    (
                        capture_start,
                        capture_end,
                        capture.group,
                        _scope_names(capture.name, match),
                    )
                )
        boundaries = {start, end}
        for a, b, _, _ in intervals:
            boundaries.update((a, b))
        for a, b, _ in retokenized:
            boundaries.update((a, b))
        retoken_index = 0
        for a, b in pairwise(sorted(boundaries)):
            active = [item for item in intervals if item[0] <= a and item[1] >= b]
            # Wider captures are outer scopes; use group order to break ties.
            active.sort(key=lambda item: (-(item[1] - item[0]), item[2]))
            segment_scopes = scopes + tuple(scope for item in active for scope in item[3])
            while retoken_index < len(retokenized) and retokenized[retoken_index][1] <= a:
                retoken_index += 1
            if retoken_index < len(retokenized):
                retoken_start, retoken_end, retoken_scopes = retokenized[retoken_index]
                if retoken_start <= a and retoken_end >= b:
                    segment_scopes = retoken_scopes
            self._emit(spans, context.offset + a, context.offset + b, segment_scopes)

    def _emit(
        self,
        spans: list[TokenSpan],
        start: int,
        end: int,
        scopes: tuple[str, ...],
    ) -> None:
        if end <= start:
            return
        if spans and spans[-1].end == start and spans[-1].scopes == scopes:
            previous = spans[-1]
            spans[-1] = TokenSpan(previous.start, end, scopes)
            return
        spans.append(TokenSpan(start, end, scopes))
        if len(spans) > self._limits.max_spans:
            raise ResourceLimitError(f'token span count exceeded {self._limits.max_spans}')


def _physical_lines(source: str) -> Iterable[tuple[int, int, int]]:
    start = 0
    for match in re.finditer(r'\r\n|\r|\n', source):
        yield start, match.start(), match.end()
        start = match.end()
    yield start, len(source), len(source)


_SCOPE_CAPTURE = re.compile(r'\$(\d+)|\$\{(\d+):/(downcase|upcase)}')


def _scope_names(name: Optional[str], match: Match) -> tuple[str, ...]:
    if not name:
        return ()
    if '$' not in name:
        return tuple(name.split())

    def expand_capture(reference: re.Match[str]) -> str:
        number = int(reference.group(1) or reference.group(2))
        try:
            value = (match.group(number) or '').lstrip('.')
        except IndexError as error:
            raise GrammarError(f'scope name references missing capture {number}') from error
        if reference.group(3) == 'downcase':
            return value.lower()
        if reference.group(3) == 'upcase':
            return value.upper()
        return value

    return tuple(_SCOPE_CAPTURE.sub(expand_capture, name).split())
