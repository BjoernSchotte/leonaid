# LeonAid proxy image

The development Compose service builds this directory. It uses the standard
Caddy 2.11.4 modules with `golang.org/x/crypto` pinned to v0.55.0. The compiler and
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
