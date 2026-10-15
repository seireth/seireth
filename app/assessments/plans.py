"""Admission-time normalization and immutable, sanitized execution plans."""

import json
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..core.constraints import (
    NormalizedMediaType,
    PluginVersion,
    StoredHttpUrl,
    TargetImage,
)
from ..plugins.base import AnalysisContext
from ..plugins.registry import registry
from ..plugins.response_context import response_applicability
from . import images
from .policy import PolicyError, ResponseUrl, bounded_url, public_response_url, validate
from .profiles import (
    ConfigModel,
    ContainerLimits,
    ContainerSpec,
    LaunchProfile,
    NetworkGrant,
    RequestProfile,
    load_config,
)


class ExpectedResponse(ConfigModel):
    final_url: ResponseUrl | None = None
    statuses: list[Annotated[int, Field(ge=100, le=599)]] = Field(
        default_factory=lambda: [200], min_length=1
    )
    media_types: list[NormalizedMediaType] = Field(
        default_factory=lambda: ["text/html"]
    )


class RoutePlan(ConfigModel):
    key: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")
    url: ResponseUrl
    plugins: list[str] = Field(min_length=1)
    request_profile: str | None = None
    expected: ExpectedResponse = Field(default_factory=ExpectedResponse)
    required_checks: list[str] | None = None
    analysis: AnalysisContext = Field(default_factory=AnalysisContext)
    request_seconds: float = Field(default=10, gt=0, le=120)


class FrozenTarget(ConfigModel):
    id: str
    project_id: str
    name: str
    kind: Literal["docker", "website"]
    image: TargetImage | None
    url: StoredHttpUrl
    launch_profile: str | None
    network_profile: str | None
    trust_profile: str | None


class PluginIdentity(ConfigModel):
    id: str
    version: PluginVersion


class FrozenRoute(RoutePlan):
    request: RequestProfile
    required_checks: list[str]
    required_checks_explicit: bool


class FrozenLaunch(ConfigModel):
    target: ContainerSpec
    services: dict[str, ContainerSpec]
    startup_seconds: float = Field(gt=0, le=600)


class FrozenPlan(ConfigModel):
    version: Literal[1]
    control_endpoints: list[dict[str, str | int]]
    target: FrozenTarget
    routes: list[FrozenRoute] = Field(min_length=1, max_length=20)
    plugins: list[PluginIdentity]
    launch: FrozenLaunch | None
    images: dict[str, TargetImage]
    network: NetworkGrant | None
    ca: str | None = Field(max_length=262144)
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    cleanup_seconds: float = Field(gt=0, allow_inf_nan=False)
    runner_limits: ContainerLimits
    policy: Literal["strict-v1"]
    baseline: str | None

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("plan version requires an integer")
        return value

    @model_validator(mode="after")
    def complete_snapshot(self):
        def check(value):
            if isinstance(value, BaseModel):
                if value.model_fields_set != type(value).model_fields.keys():
                    raise ValueError(
                        "frozen configuration must contain every resolved field"
                    )
                for name in type(value).model_fields:
                    check(getattr(value, name))
            elif isinstance(value, dict):
                for item in value.values():
                    check(item)
            elif isinstance(value, (tuple, list)):
                for item in value:
                    check(item)

        check(self)
        if any(route.expected.final_url is None for route in self.routes):
            raise ValueError("frozen routes require a final response URL")
        if self.target.kind == "docker":
            if self.launch is None or set(self.images) != {
                "target",
                "runner",
                *self.launch.services,
            }:
                raise ValueError("Docker plans require a complete pinned bundle")
            import re

            if any(
                not re.fullmatch(r"sha256:[0-9a-f]{64}", image)
                for image in self.images.values()
            ):
                raise ValueError("Docker plans require immutable image IDs")
        elif self.launch is not None or self.images:
            raise ValueError("website plans cannot contain a Docker bundle")
        return self


def required_checks(route: RoutePlan, plugins) -> list[str]:
    available = {
        f"{plugin.manifest.id}:{rule}" for plugin in plugins for rule in plugin.rules
    }
    if route.required_checks is not None:
        if (
            len(set(route.required_checks)) != len(route.required_checks)
            or set(route.required_checks) - available
        ):
            raise PolicyError(
                "required checks must be unique rules from the selected plugins"
            )
        return route.required_checks

    def potentially_applicable(applicability):
        for status in route.expected.statuses:
            for media in route.expected.media_types or [None]:
                result = response_applicability(applicability, status, media)
                if result is None or result[0] == "inconclusive":
                    return True
        return False

    return [
        f"{plugin.manifest.id}:{rule}"
        for plugin in plugins
        for rule, applicability in plugin.rules.items()
        if (
            applicability in {"document", "representation"}
            and potentially_applicable(applicability)
        )
        or (
            applicability == "session"
            and bool(
                set(route.analysis.expected_cookies)
                & set(route.analysis.session_cookies)
            )
        )
        or (
            applicability in {"cookie-presence", "cookie-observation"}
            and bool(route.analysis.expected_cookies)
        )
    ]


def freeze_plan(
    project,
    target,
    routes: list[RoutePlan],
    *,
    timeout_seconds=None,
    baseline=None,
    control_endpoint=None,
) -> dict:
    from ..core.config import settings

    if not 1 <= len(routes) <= 20 or len({route.key for route in routes}) != len(
        routes
    ):
        raise PolicyError("plan requires 1 to 20 uniquely keyed routes")
    config = load_config()
    controls = []
    if control_endpoint:
        import ipaddress

        try:
            controls.append(
                {
                    "address": str(ipaddress.ip_address(control_endpoint[0])),
                    "port": int(control_endpoint[1]),
                }
            )
        except ValueError, TypeError:
            pass
    public_routes, selected = [], {}
    for route in routes:
        validate(project, target, str(route.url))
        if route.expected.final_url:
            validate(project, target, str(route.expected.final_url))
        plugins = registry.select(route.plugins)
        for plugin in plugins:
            selected[plugin.manifest.id] = plugin.manifest.version
        profile = RequestProfile()
        if route.request_profile:
            if route.request_profile not in config.requests:
                raise PolicyError("request profile is unavailable")
            profile = config.requests[route.request_profile]
        if set(profile.secret_headers.values()) - config.secrets.keys():
            raise PolicyError("request profile contains unknown secret references")
        public_routes.append(
            {
                **route.model_dump(mode="json"),
                "request": profile.model_dump(mode="json"),
                "required_checks": required_checks(route, plugins),
                "required_checks_explicit": route.required_checks is not None,
            }
        )
        public_routes[-1]["expected"]["final_url"] = public_response_url(
            route.expected.final_url or route.url
        )
    target_data = {
        key: getattr(target, key)
        for key in (
            "id",
            "project_id",
            "name",
            "kind",
            "image",
            "url",
            "launch_profile",
            "network_profile",
            "trust_profile",
        )
    }
    launch = None
    pinned = {}
    limits = ContainerLimits(
        memory=settings.docker_memory,
        cpus=settings.docker_cpus,
        pids=settings.docker_pids_limit,
    ).model_dump()
    if target.kind == "docker":

        @cache
        def inspect_image(image):
            return images.inspect_image(image)

        if target.launch_profile and target.launch_profile not in config.launches:
            raise PolicyError("launch profile is unavailable")
        launch_model = config.launches.get(target.launch_profile, LaunchProfile())
        launch = launch_model.model_dump(mode="json")
        original_specs = {"target": launch_model.target, **launch_model.services}
        for name, spec in {"target": launch["target"], **launch["services"]}.items():
            for key, value in limits.items():
                if key not in original_specs[name].model_fields_set:
                    spec[key] = value
        launch["target"]["image"] = target.image
        if launch["target"]["readiness"] is None:
            from urllib.parse import urlsplit

            parsed = urlsplit(target.url)
            launch["target"]["readiness"] = {
                "kind": "tcp",
                "port": parsed.port or (443 if parsed.scheme == "https" else 80),
                "path": "/",
                "status": 200,
            }
        specs = {"target": launch["target"], **launch["services"]}
        for name, spec in specs.items():
            if set(spec["secret_environment"].values()) - config.secrets.keys():
                raise PolicyError("launch profile contains unknown secret references")
            metadata = inspect_image(spec["image"])
            declared = {volume["path"] for volume in spec["volumes"]}
            if set(metadata.get("Config", {}).get("Volumes") or {}) - declared:
                raise PolicyError(
                    "image declares an anonymous volume; declare every writable volume in the launch profile"
                )
            pinned[name] = metadata["Id"]
        pinned["runner"] = inspect_image(settings.bundle_runner_image)["Id"]
    network = None
    if target.network_profile:
        if target.network_profile not in config.networks:
            raise PolicyError("network profile is unavailable")
        network = config.networks[target.network_profile].model_dump()
        if not bounded_url(target.url, network["url"]):
            raise PolicyError("target is outside the network grant")
    ca = None
    if target.trust_profile:
        try:
            ca = Path(config.trusts[target.trust_profile].file).read_text(
                encoding="ascii"
            )
            if len(ca) > 262144:
                raise ValueError()
            import ssl

            ssl.create_default_context(cadata=ca)
        except Exception:
            raise PolicyError("configured certificate trust is unavailable") from None
    startup = launch["startup_seconds"] if launch else 0
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else min(900, startup + sum(route.request_seconds + 5 for route in routes))
    )
    return FrozenPlan.model_validate(
        {
            "version": 1,
            "control_endpoints": controls,
            "target": target_data,
            "routes": public_routes,
            "plugins": [
                {"id": key, "version": version} for key, version in selected.items()
            ],
            "launch": launch,
            "images": pinned,
            "network": network,
            "ca": ca,
            "timeout_seconds": timeout,
            "cleanup_seconds": settings.cleanup_timeout_seconds,
            "runner_limits": limits,
            "policy": "strict-v1",
            "baseline": baseline,
        }
    ).model_dump(mode="json")


def read_snapshot(snapshot: dict) -> FrozenPlan:
    """Validate stored JSON strictly, without reconstructing missing defaults."""
    return FrozenPlan.model_validate_json(json.dumps(snapshot), strict=True)


def verify_snapshot(snapshot: dict) -> dict:
    snapshot = read_snapshot(snapshot).model_dump(mode="json")
    try:
        plugins = registry.select([entry["id"] for entry in snapshot["plugins"]])
    except ValueError:
        raise PolicyError("queued plugin selection is unavailable") from None
    if {plugin.manifest.id: plugin.manifest.version for plugin in plugins} != {
        entry["id"]: entry["version"] for entry in snapshot["plugins"]
    }:
        raise PolicyError("installed plugin versions differ from the queued plan")
    return snapshot
