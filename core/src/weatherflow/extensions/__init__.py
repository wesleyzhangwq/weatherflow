"""Verified local extension packages and credential references."""

from weatherflow.extensions.catalog import (
    SkillCatalogEntry,
    SkillCatalogError,
    SkillCatalogService,
    WesleySkillCatalog,
)
from weatherflow.extensions.credentials import (
    CredentialBroker,
    CredentialRef,
    CredentialStore,
    CredentialUnavailableError,
    KeyringCredentialStore,
    MappingCredentialStore,
    NativeCredentialResolver,
    WritableCredentialStore,
)
from weatherflow.extensions.installer import (
    PackageInstaller,
    PackageInstallExecutor,
    package_install_tool_spec,
)
from weatherflow.extensions.models import (
    AgentDefinitionPackageManifest,
    CapabilityPackManifest,
    InstalledPackage,
    PackageFile,
    PackageManifest,
    SkillPackageManifest,
)
from weatherflow.extensions.store import PackageIntegrityError, PackageStore

__all__ = [
    "AgentDefinitionPackageManifest",
    "CapabilityPackManifest",
    "CredentialBroker",
    "CredentialRef",
    "CredentialStore",
    "CredentialUnavailableError",
    "KeyringCredentialStore",
    "InstalledPackage",
    "MappingCredentialStore",
    "NativeCredentialResolver",
    "WritableCredentialStore",
    "PackageFile",
    "PackageInstaller",
    "PackageInstallExecutor",
    "PackageIntegrityError",
    "PackageManifest",
    "PackageStore",
    "SkillCatalogEntry",
    "SkillCatalogError",
    "SkillCatalogService",
    "SkillPackageManifest",
    "WesleySkillCatalog",
    "package_install_tool_spec",
]
