class RegistryError(LookupError):
    """Indicate an invalid plugin registration or lookup operation."""


class DuplicatePluginError(RegistryError):
    """Indicate that a plugin name is already registered."""

    pass


class UnknownPluginError(RegistryError):
    """Indicate that a requested plugin name is not registered."""

    pass
