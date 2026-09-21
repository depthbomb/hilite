from typing import Optional
from collections.abc import Sequence

ONIGURUMA_VERSION: str

class Pattern:
    def __init__(self, pattern: str) -> None: ...

class Scanner:
    def __init__(self, patterns: Sequence[Pattern]) -> None: ...
    def find(
        self,
        line: Line,
        position: int,
        first: bool,
        anchored: bool,
        timeout: Optional[float],
    ) -> Optional[tuple[int, Match]]: ...

class Line:
    def __init__(self, text: str) -> None: ...
    def search(
        self,
        pattern: Pattern,
        position: int,
        first: bool,
        anchored: bool,
        timeout: Optional[float],
    ) -> Optional[Match]: ...

class Match:
    def start(self, group: Optional[int | str] = None) -> int: ...
    def end(self, group: Optional[int | str] = None) -> int: ...
    def group(self, group: Optional[int | str] = None) -> Optional[str]: ...
    def groups(self) -> tuple[Optional[str], ...]: ...
