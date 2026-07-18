import re


class TextFragmenter:
    def __init__(self, min_chars: int, max_chars: int):
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.buffer = ""

    def add(self, text: str, *, timed_out: bool = False) -> list[str]:
        self.buffer += text
        fragments = []
        while len(self.buffer) >= self.min_chars:
            split = self._split_at(timed_out)
            if split is None:
                break
            fragments.append(self.buffer[:split])
            self.buffer = self.buffer[split:]
            timed_out = False
        return fragments

    def finish(self) -> list[str]:
        if not self.buffer:
            return []
        fragment, self.buffer = self.buffer, ""
        return [fragment]

    def _split_at(self, timed_out: bool) -> int | None:
        window = self.buffer[: self.max_chars]
        for pattern in (r"[.!?…\n](?:\s|$)", r"[,;:](?:\s|$)"):
            matches = list(re.finditer(pattern, window))
            valid = [match.end() for match in matches if match.end() >= self.min_chars]
            if valid:
                return valid[-1]
        spaces = [match.end() for match in re.finditer(r"\s+", window)]
        valid = [position for position in spaces if position >= self.min_chars]
        if len(self.buffer) > self.max_chars:
            return valid[-1] if valid else self.max_chars
        if timed_out:
            return valid[-1] if valid else len(window)
        return None
