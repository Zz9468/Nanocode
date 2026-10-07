from typing import Any, Protocol


class Driver(Protocol):
    def connect(self) -> Any: ...

