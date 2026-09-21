from time import monotonic
from threading import RLock
from dataclasses import dataclass
from collections import OrderedDict
from collections.abc import Sequence
from hilite.tokenizer import Tokenizer
from hilite.rendering import render_html
from hilite.errors import ResourceLimitError
from hilite.grammar import Grammar, GrammarCompiler, GrammarRegistry, PreparedGrammar
from hilite.models import (
    Theme,
    ThemeRule,
    HtmlLayout,
    LineOptions,
    TokenizedCode,
    ResourceLimits,
)


@dataclass(frozen=True, slots=True)
class CacheInfo:
    prepared_grammars: int
    dynamic_patterns: int
    max_prepared_grammars: int


class Highlighter:
    def __init__(
        self,
        registry: GrammarRegistry | None = None,
        *,
        limits: ResourceLimits | None = None,
        max_prepared_grammars: int = 32,
    ) -> None:
        if type(max_prepared_grammars) is not int or max_prepared_grammars < 1:
            raise ValueError('max_prepared_grammars must be positive')
        self.registry = registry if registry is not None else GrammarRegistry()
        if registry is None:
            self.registry.register_dict(
                {'scopeName': 'text.plain', 'patterns': []},
                language='plain',
                aliases=('text', 'plaintext'),
            )
        self.limits = limits or ResourceLimits()
        self._max_prepared = max_prepared_grammars
        self._prepared: OrderedDict[str, PreparedGrammar] = OrderedDict()
        self._validated: set[str] = set()
        self._lock = RLock()
        self._registry_revision = self.registry.revision
        self._tokenizer = Tokenizer(
            self._prepared_for_scope,
            self.registry.injections_for,
            self.limits,
        )

    def register(self, grammar: Grammar, *, replace: bool = False) -> None:
        self.registry.register(grammar, replace=replace)
        self.clear_cache()

    def tokenize(self, source: str, *, language: str) -> TokenizedCode:
        deadline = (
            monotonic() + self.limits.timeout_seconds
            if self.limits.timeout_seconds is not None
            else None
        )
        if not isinstance(source, str):
            raise TypeError('source must be a string')
        if len(source) > self.limits.max_input_chars:
            raise ResourceLimitError('input contains more characters than max_input_chars')
        self._sync_registry()
        grammar = self.registry.get(language)
        prepared = self._prepare(grammar)
        self._validate(prepared)
        return self._tokenizer.tokenize(source, prepared, deadline=deadline)

    def validate(self, language: str) -> None:
        self._sync_registry()
        grammar = self.registry.get(language)
        prepared = self._prepare(grammar)
        self._validate(prepared)

    def highlight(
        self,
        source: str,
        *,
        language: str,
        theme: Theme | None = None,
        overrides: Sequence[ThemeRule] = (),
        layout: HtmlLayout | None = None,
        lines: LineOptions | None = None,
    ) -> str:
        tokenized = self.tokenize(source, language=language)
        return render_html(
            tokenized,
            theme=theme,
            overrides=overrides,
            layout=layout,
            lines=lines,
        )

    def clear_cache(self) -> None:
        with self._lock:
            self._prepared.clear()
            self._validated.clear()
        self._tokenizer.clear()

    def cache_info(self) -> CacheInfo:
        with self._lock:
            return CacheInfo(
                len(self._prepared),
                self._tokenizer.dynamic_pattern_count,
                self._max_prepared,
            )

    def _validate(self, prepared: PreparedGrammar) -> None:
        scope_name = prepared.grammar.scope_name
        with self._lock:
            validated = scope_name in self._validated
        if not validated:
            self._tokenizer.validate(prepared)
            with self._lock:
                if scope_name in self._prepared:
                    self._validated.add(scope_name)

    def _sync_registry(self) -> None:
        with self._lock:
            if self._registry_revision != self.registry.revision:
                # Other grammars may include the changed grammar, so clear their caches too.
                self.clear_cache()
                self._registry_revision = self.registry.revision

    def _prepared_for_scope(self, scope_name: str) -> PreparedGrammar:
        return self._prepare(self.registry.get(scope_name))

    def _prepare(self, grammar: Grammar) -> PreparedGrammar:
        with self._lock:
            prepared = self._prepared.get(grammar.scope_name)
            if prepared is not None:
                self._prepared.move_to_end(grammar.scope_name)
                return prepared
        # Let other callers use cached grammars while this one compiles.
        prepared = GrammarCompiler(self.limits).compile(grammar)
        with self._lock:
            # Another caller may have finished compiling the same grammar in the meantime.
            existing = self._prepared.get(grammar.scope_name)
            if existing is not None:
                self._prepared.move_to_end(grammar.scope_name)
                return existing
            self._prepared[grammar.scope_name] = prepared
            while len(self._prepared) > self._max_prepared:
                scope, _ = self._prepared.popitem(last=False)
                self._validated.discard(scope)
        return prepared


def highlight(
    source: str,
    *,
    language: str,
    registry: GrammarRegistry,
    theme: Theme | None = None,
    overrides: Sequence[ThemeRule] = (),
    layout: HtmlLayout | None = None,
    lines: LineOptions | None = None,
    limits: ResourceLimits | None = None,
) -> str:
    return Highlighter(registry, limits=limits).highlight(
        source,
        language=language,
        theme=theme,
        overrides=overrides,
        layout=layout,
        lines=lines,
    )
