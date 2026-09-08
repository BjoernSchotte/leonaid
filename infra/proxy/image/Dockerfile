FROM --platform=$BUILDPLATFORM docker.io/library/caddy:2.11.4-builder-alpine@sha256:1a1689db91cfb390b2d856a1b3774e796852822cd723fa54c475b272f82bb4b7 AS build
WORKDIR /src
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=1
COPY go.mod go.sum ./
RUN go mod download && go mod verify
COPY main.go ./
ARG TARGETOS
ARG TARGETARCH
RUN GOOS=$TARGETOS GOARCH=$TARGETARCH go build -mod=readonly -p=1 -trimpath -ldflags='-w -s' -o /out/caddy .
FROM docker.io/library/caddy:2.11.4-alpine@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648
COPY --from=build /out/caddy /usr/bin/caddy
