# LeonAid proxy image

The development Compose service builds this directory. It uses the standard
Caddy 2.11.7 modules with `golang.org/x/crypto` pinned to v0.58.0 and
`golang.org/x/net` pinned to v0.62.0 (CVE-2026-78661). The compiler and
runtime base images are pinned by digest, and `go.sum` locks module content.
The runtime base supplies the operating system; its Caddy executable is replaced
by the executable compiled here. `CADDY_IMAGE` remains the upstream base pin,
not the identity of the resulting LeonAid proxy image.

The builder runs on the build platform and cross-compiles for `TARGETOS` and
`TARGETARCH`, with CGO disabled. Dependency downloads are verified before the
read-only module build. No plugin download or compilation occurs at runtime.

Production requires `LEONAID_PROXY_IMAGE` to identify the built release image by
digest. The pilot overlay disables builds, and the release manifest binds the
proxy image alongside the application images. Isolated operator tests resolve
their project-owned proxy image to an immutable image ID before manifest creation.
Restoration uses the source image identity and must not rebuild the proxy.

`tools/proxy/export-image.sh` builds this same Dockerfile and exports its exact
image ID without a shared tag. The security scanner and Caddy SBOM generator use
that archive. The Critical vulnerability gate is unchanged and uses no VEX or
vulnerability exclusion. A passing configured gate is not a claim that every
possible vulnerability is absent.

The proxy service runs with `init: true`. Caddy as PID 1 does not reap foreign
children, and BusyBox `wget` in the HTTPS healthcheck leaves an orphaned
`ssl_client` helper per run. Without an init process these zombies fill
`pids_limit` within minutes, and the Go runtime then aborts with
`fatal error: newosproc`. Caddy itself needs about 10 to 15 threads under
load (Go 1.26 sets `GOMAXPROCS` from the CPU quota; CGO is disabled, so DNS
uses the pure-Go resolver). `tools/ci/proxy-runtime.sh` runs the built image
under the service limits with concurrent file_server load and repeated
healthchecks, and fails on any zombie or a pids peak above half the limit.
