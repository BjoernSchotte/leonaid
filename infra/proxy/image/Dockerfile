FROM --platform=$BUILDPLATFORM docker.io/library/caddy:2.11.4-builder-alpine@sha256:0aa610043dab5da82ad0a0268e46bb852785e6f5160f12f1c6fe3f42903d7e1b AS build
WORKDIR /src
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=1
COPY go.mod go.sum ./
RUN go mod download && go mod verify
COPY main.go ./
ARG TARGETOS
ARG TARGETARCH
RUN GOOS=$TARGETOS GOARCH=$TARGETARCH go build -mod=readonly -p=1 -trimpath -ldflags='-w -s' -o /out/caddy .
FROM docker.io/library/caddy:2.11.4-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b
COPY --from=build /out/caddy /usr/bin/caddy
# Upstream caddy:2.11.4-alpine still ships brotli-libs 1.2.0-r0 (CVE-2026-111497).
RUN apk upgrade --no-cache brotli-libs
