from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from control_plane.application.command_support import IdempotencyRepository
from control_plane.application.ports.repositories import (
    ComponentRepository,
    CredentialRepository,
)

ComponentCommandScope = Callable[
    [], AbstractAsyncContextManager[tuple[ComponentRepository, IdempotencyRepository]]
]

CredentialCommandScope = Callable[
    [], AbstractAsyncContextManager[tuple[CredentialRepository, IdempotencyRepository]]
]
