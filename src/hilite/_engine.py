from hilite._oniguruma import Pattern
from hilite.errors import UnsupportedPatternError


def compile_pattern(pattern: str, *, grammar: str, rule_path: str) -> Pattern:
    try:
        return Pattern(pattern)
    except ValueError as error:
        raise UnsupportedPatternError(
            f'{grammar} {rule_path}: oniguruma rejected {pattern!r}: {error}'
        ) from error
