FROM --platform=$BUILDPLATFORM docker.io/library/caddy:2.11.7-builder-alpine@sha256:95a5e7e2692b5eb9545aadc5b90a39f6f509bee59c9508a493f83ee902eaef63 AS build
WORKDIR /src
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=1
COPY go.mod go.sum ./
RUN go mod download && go mod verify
COPY main.go ./
ARG TARGETOS
ARG TARGETARCH
RUN GOOS=$TARGETOS GOARCH=$TARGETARCH go build -mod=readonly -p=1 -trimpath -ldflags='-w -s' -o /out/caddy .
FROM docker.io/library/caddy:2.11.7-alpine@sha256:e70b164da81ef698b3ad19af799ea6086ce6d9e48ed4079eb9fe26f6fbf14ee5
COPY --from=build /out/caddy /usr/bin/caddy
# Upstream caddy:2.11.7-alpine still ships brotli-libs 1.2.0-r0 (CVE-2026-111497).
RUN apk upgrade --no-cache brotli-libs
