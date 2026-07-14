from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@total_ordering
@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> "Version":
        match = _SEMVER.fullmatch(str(value).strip())
        if not match:
            raise ValueError(f"Invalid semantic version {value!r}; expected MAJOR.MINOR.PATCH")
        return cls(*(int(part) for part in match.groups()))

    def bump(self, part: str = "patch") -> "Version":
        if part == "patch":
            return Version(self.major, self.minor, self.patch + 1)
        if part == "minor":
            return Version(self.major, self.minor + 1, 0)
        if part == "major":
            return Version(self.major + 1, 0, 0)
        raise ValueError(f"Unsupported version bump: {part}")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

