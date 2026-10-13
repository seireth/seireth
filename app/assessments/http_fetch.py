"""Shared header-only GET transport with DNS pinning and preserved Host/SNI."""

import asyncio
import ipaddress
import ssl
from time import monotonic
from urllib.parse import urljoin, urlsplit

import dns.asyncresolver
import httpcore
import httpx

from ..plugins.base import HttpObservation
from .policy import PolicyError, bounded_url, http_origin, public_response_url


async def resolve(host: str) -> list[str]:
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    try:
        resolver = dns.asyncresolver.Resolver()
        answer = await resolver.resolve_name(host, lifetime=5)
        return list(answer.addresses())
    except Exception:
        raise PolicyError("destination DNS resolution failed") from None


class PinnedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, authorize, mapping=None):
        self.backend = httpcore.AnyIOBackend()
        self.authorize = authorize
        self.mapping = mapping or {}

    async def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        name = host
        deadline = monotonic() + (timeout if timeout is not None else 10)
        addresses = await resolve(self.mapping.get(name, name))
        addresses = list(dict.fromkeys(addresses))
        if not addresses or len(addresses) > 32:
            raise PolicyError("destination has no approved addresses")
        self.authorize(name, port, addresses)
        # Connect only to an address actually checked above; never resolve the
        # original hostname again between authorization and the connection.
        for index, address in enumerate(addresses):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("destination connection timed out")
            try:
                return await self.backend.connect_tcp(
                    address,
                    port,
                    remaining / (len(addresses) - index),
                    local_address,
                    socket_options,
                )
            except httpcore.ConnectError, httpcore.ConnectTimeout:
                continue
        raise PolicyError("approved destination addresses could not be reached")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


class CoreTransport(httpx.AsyncBaseTransport):
    def __init__(self, backend, ca=None):
        context = ssl.create_default_context(cadata=ca)
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = True
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=context,
            network_backend=backend,
            max_connections=1,
            max_keepalive_connections=0,
        )

    async def handle_async_request(self, request):
        result = await self.pool.handle_async_request(
            httpcore.Request(
                method=request.method,
                url=httpcore.URL(
                    scheme=request.url.raw_scheme,
                    host=request.url.raw_host,
                    port=request.url.port,
                    target=request.url.raw_path,
                ),
                headers=request.headers.raw,
                content=request.stream,
                extensions=request.extensions,
            )
        )

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                async for chunk in result.stream:
                    yield chunk

            async def aclose(self):
                await result.aclose()

        return httpx.Response(
            result.status,
            headers=result.headers,
            stream=Stream(),
            extensions=result.extensions,
        )

    async def aclose(self):
        await self.pool.aclose()


async def fetch(
    url,
    *,
    registered,
    headers=None,
    follow_redirects=False,
    timeout=10,
    authorize,
    mapping=None,
    ca=None,
) -> dict:
    async with asyncio.timeout(timeout):
        # Honor pending cancellation before creating transport resources.
        await asyncio.sleep(0)
        backend = PinnedBackend(authorize, mapping)
        transport = CoreTransport(backend, ca)
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=timeout,
        ) as client:
            current, chain = url, []
            for hop in range(6):
                if not bounded_url(current, registered):
                    raise PolicyError(
                        "redirect destination is outside the registered target"
                    )
                async with client.stream(
                    "GET", current, headers=headers or {}
                ) as response:
                    fields = {}
                    size = 0
                    for name, value in response.headers.raw:
                        size += len(name) + len(value)
                        if size > 65536:
                            raise PolicyError(
                                "response headers exceed the observation budget"
                            )
                        fields.setdefault(name.decode("ascii").lower(), []).append(
                            value.decode("latin-1")
                        )
                    public_url = public_response_url(current)
                    observation = HttpObservation(
                        url=public_url, status_code=response.status_code, headers=fields
                    )
                    location = response.headers.get("location")
                    if (
                        follow_redirects
                        and response.status_code in {301, 302, 303, 307, 308}
                        and location
                    ):
                        destination = urljoin(current, location)
                        if hop == 5:
                            raise PolicyError("redirect limit exceeded")
                        if not bounded_url(destination, registered):
                            raise PolicyError(
                                "redirect destination is outside the registered target"
                            )
                        # Query values and response header contents are not stored
                        # in the redirect history.
                        chain.append(
                            {"url": public_url, "status_code": response.status_code}
                        )
                        current = destination
                        continue
                    return {"observation": observation, "redirects": chain}
            raise PolicyError("redirect limit exceeded")


def website_authorizer(snapshot, config, control_origin, runtime_addresses=()):
    frozen = snapshot["network"]
    registered = snapshot["target"]["url"]
    origin = http_origin(urlsplit(registered))
    controls = snapshot["control_endpoints"]
    ports = {control_origin[2], *(entry["port"] for entry in controls)}
    protected = {(entry["address"], entry["port"]) for entry in controls}
    protected.update((address, port) for address in runtime_addresses for port in ports)

    def authorize(host, port, addresses):
        active = config()
        current = active.networks.get(snapshot["target"]["network_profile"])
        trust = snapshot["target"]["trust_profile"]
        if trust and trust not in active.trusts:
            raise PolicyError("certificate trust permission is no longer available")
        if port in {2375, 2376}:
            raise PolicyError("Docker control endpoints cannot be assessed")
        if (origin[0], host, port) != origin:
            raise PolicyError("connection is outside the target origin")
        if control_origin[1] == host and control_origin[2] == port:
            raise PolicyError("Seireth control endpoints cannot be assessed")
        for text in addresses:
            if (text, port) in protected:
                raise PolicyError("Seireth control endpoints cannot be assessed")
            address = ipaddress.ip_address(text)
            if address.version == 6 and address.ipv4_mapped:
                address = address.ipv4_mapped
            if (str(address), port) in protected:
                raise PolicyError("Seireth control endpoints cannot be assessed")
            if (
                address.is_link_local
                or address.is_multicast
                or address.is_unspecified
                or address
                in {
                    ipaddress.ip_address("169.254.169.254"),
                    ipaddress.ip_address("fd00:ec2::254"),
                }
            ):
                raise PolicyError("destination address is forbidden")
            if address.is_loopback and port == control_origin[2]:
                raise PolicyError("Seireth control endpoints cannot be assessed")
            if address.is_global:
                continue
            if not frozen or not current or not bounded_url(registered, current.url):
                raise PolicyError(
                    "private destination requires an active network grant"
                )
            for grants in (frozen["cidrs"], current.cidrs):
                if not any(address in ipaddress.ip_network(cidr) for cidr in grants):
                    raise PolicyError(
                        "destination address is outside the network grant"
                    )

    return authorize
