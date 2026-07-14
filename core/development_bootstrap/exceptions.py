from __future__ import annotations


class BootstrapError(RuntimeError):
    def __init__(self, message: str, *, hint: str = "", log_path: str = ""):
        super().__init__(message)
        self.hint = hint
        self.log_path = log_path

    def render(self) -> str:
        lines = [str(self)]
        if self.log_path:
            lines.append(f"Log: {self.log_path}")
        if self.hint:
            lines.append(f"Next step: {self.hint}")
        return "\n".join(lines)
