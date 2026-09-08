from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from control_plane.application.command_support import IdempotencyRepository
from control_plane.application.ports.repositories import (
    ComponentRepository,
    CredentialRepository,
    LiveComponentRepository,
    PlatformRepository,
    ProviderRepository,
    SystemConfigurationRepository,
)

ComponentCommandScope = Callable[
    [], AbstractAsyncContextManager[tuple[ComponentRepository, IdempotencyRepository]]
]

CredentialCommandScope = Callable[
    [], AbstractAsyncContextManager[tuple[CredentialRepository, IdempotencyRepository]]
]

ProviderCommandScope = Callable[
    [], AbstractAsyncContextManager[tuple[ProviderRepository, IdempotencyRepository]]
]

LiveComponentCommandScope = Callable[
    [],
    AbstractAsyncContextManager[tuple[LiveComponentRepository, IdempotencyRepository]],
]

SystemConfigurationCommandScope = Callable[
    [],
    AbstractAsyncContextManager[
        tuple[SystemConfigurationRepository, IdempotencyRepository]
    ],
]

PlatformCommandScope = Callable[
    [], AbstractAsyncContextManager[tuple[PlatformRepository, IdempotencyRepository]]
]
