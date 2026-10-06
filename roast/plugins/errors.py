class RegistrationError(ValueError):
    """Indicate an invalid plugin registration operation."""


class DuplicatePluginError(RegistrationError):
    """Indicate that a plugin name is already registered."""


class UnknownPluginError(LookupError):
    """Indicate that a requested plugin name is not registered."""


class ManifestError(ValueError):
    """Report an invalid or unresolved declarative manifest."""
