"""Operator-owned configuration. Public snapshots contain references, never secrets."""

import os
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from ..core.constraints import TargetImage
from .policy import PolicyError, bounded_url


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class SecretRef(ConfigModel):
    env: str | None = None
    file: str | None = None

    @model_validator(mode="after")
    def one_source(self):
        if (self.env is None) == (self.file is None):
            raise ValueError("secret reference requires exactly one source")
        return self


class RequestProfile(ConfigModel):
    headers: dict[str, str] = Field(default_factory=dict)
    secret_headers: dict[str, str] = Field(default_factory=dict)
    follow_redirects: bool = False

    @model_validator(mode="after")
    def safe_headers(self):
        forbidden = {"host", "content-length", "transfer-encoding", "connection"}
        for name, value in {**self.headers, **self.secret_headers}.items():
            if not name or any(c in name + value for c in "\r\n\x00"):
                raise ValueError("invalid request header")
            if name.lower() in forbidden:
                raise ValueError("transport headers cannot be overridden")
        if any(
            name.lower() in {"authorization", "cookie", "proxy-authorization"}
            for name in self.headers
        ):
            raise ValueError("credentials require secret references")
        names = [name.lower() for name in (*self.headers, *self.secret_headers)]
        if len(names) != len(set(names)):
            raise ValueError("request header names must be unique")
        return self


class NetworkGrant(ConfigModel):
    url: str
    cidrs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def safe_grant(self):
        from ipaddress import ip_network

        if not bounded_url(self.url, self.url):
            raise ValueError("invalid network grant URL")
        for cidr in self.cidrs:
            ip_network(cidr)
        return self


class TrustRef(ConfigModel):
    file: str


def validate_container_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value.startswith("/")
        or any(character in value for character in ",:\\")
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or ".." in path.parts
        or len(path.parts) == 1
        or path.parts[1] in {"proc", "sys", "dev"}
    ):
        raise ValueError("unsafe container mount path")
    return "/" + "/".join(path.parts[1:])


ContainerPath = Annotated[str, AfterValidator(validate_container_path)]


class VolumeSpec(ConfigModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    path: ContainerPath


class Readiness(ConfigModel):
    kind: Literal["tcp", "http", "https"] = "tcp"
    port: int = Field(ge=1, le=65535)
    path: str = "/"
    status: int = Field(default=200, ge=100, le=599)


class ContainerLimits(ConfigModel):
    memory: str = Field(
        default="256m",
        pattern=r"^[1-9][0-9]*(?:[bBkKmMgGtT](?:[iI]?[bB])?)?$",
        max_length=20,
    )
    cpus: float = Field(default=0.5, gt=0, allow_inf_nan=False)
    pids: int = Field(default=64, ge=1, le=2147483647)


class ContainerSpec(ContainerLimits):
    image: TargetImage | None = None
    command: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    secret_environment: dict[str, str] = Field(default_factory=dict)
    uid: int = Field(default=65532, ge=1, le=2147483647)
    gid: int = Field(default=65532, ge=1, le=2147483647)
    volumes: list[VolumeSpec] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    readiness: Readiness | None = None
    tmpfs: list[ContainerPath] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def valid_environment(self):
        import re

        if any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
            for name in (*self.environment, *self.secret_environment)
        ):
            raise ValueError("invalid environment variable name")
        if set(self.environment) & self.secret_environment.keys():
            raise ValueError("environment variable definitions must be unique")
        return self


def dependency_order(dependencies: dict[str, list[str]]) -> list[str]:
    """Validate declared dependencies and return deterministic startup order."""
    if any(set(names) - dependencies.keys() for names in dependencies.values()):
        raise ValueError("invalid service dependency graph")
    pending, ordered = set(dependencies), []
    while pending:
        ready = sorted(
            name for name in pending if not set(dependencies[name]) & pending
        )
        if not ready:
            raise ValueError("invalid service dependency graph")
        ordered.extend(ready)
        pending -= set(ready)
    return ordered


class LaunchProfile(ConfigModel):
    target: ContainerSpec = Field(default_factory=ContainerSpec)
    services: dict[str, ContainerSpec] = Field(default_factory=dict, max_length=8)
    startup_seconds: float = Field(default=60, gt=0, le=600)

    @model_validator(mode="after")
    def valid_graph(self):
        import re

        if any(
            not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", name)
            or name in {"target", "runner", "initializer", "network"}
            or name.startswith("volume-")
            for name in self.services
        ):
            raise ValueError("invalid service name")
        specs = {**self.services, "target": self.target}
        if self.target.image is not None:
            raise ValueError(
                "launch profile target image is selected by the registered target"
            )
        if any(spec.image is None for spec in self.services.values()):
            raise ValueError("service images are required")
        volumes = [volume.name for spec in specs.values() for volume in spec.volumes]
        if len(volumes) > 16 or len(volumes) != len(set(volumes)):
            raise ValueError("at most 16 distinct owned volumes are supported")
        dependency_order({name: spec.depends_on for name, spec in specs.items()})
        return self


class OperatorConfig(ConfigModel):
    requests: dict[str, RequestProfile] = Field(default_factory=dict)
    launches: dict[str, LaunchProfile] = Field(default_factory=dict)
    networks: dict[str, NetworkGrant] = Field(default_factory=dict)
    trusts: dict[str, TrustRef] = Field(default_factory=dict)
    secrets: dict[str, SecretRef] = Field(default_factory=dict)


def load_config() -> OperatorConfig:
    from ..core.config import settings

    if not settings.operator_config_file:
        return OperatorConfig()
    try:
        return OperatorConfig.model_validate_json(
            Path(settings.operator_config_file).read_text(encoding="utf-8")
        )
    except Exception:
        raise PolicyError("operator configuration is invalid or unavailable") from None


def resolve_secret(name: str, config: OperatorConfig, *, header=False) -> str:
    try:
        ref = config.secrets[name]
        value = (
            os.environ[ref.env]
            if ref.env
            else Path(ref.file).read_text(encoding="utf-8").rstrip("\r\n")
        )
        if (
            not value
            or len(value) > 65536
            or "\x00" in value
            or (header and any(c in value for c in "\r\n"))
        ):
            raise ValueError()
        return value
    except Exception:
        raise PolicyError("required runtime secret is unavailable") from None


def resolve_headers(profile, config):
    return {
        **profile["headers"],
        **{
            name: resolve_secret(ref, config, header=True)
            for name, ref in profile["secret_headers"].items()
        },
    }


def public_catalog() -> dict:
    config = load_config()
    return {
        "requests": {
            name: profile.model_dump(mode="json")
            for name, profile in config.requests.items()
        },
        "launches": {
            name: profile.model_dump(mode="json")
            for name, profile in config.launches.items()
        },
        "networks": {
            name: grant.model_dump(mode="json")
            for name, grant in config.networks.items()
        },
        "trusts": list(config.trusts),
    }
