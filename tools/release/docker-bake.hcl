// Release images for one LeonAid version, pushed by .github/workflows/release.yml.
// The production environment pins each as <registry>/<name>:<version>@sha256:<digest>.
variable "REGISTRY" { default = "ghcr.io/bjoernschotte/leonaid" }
variable "VERSION" { default = "0.0.0-dev" }
variable "REVISION" { default = "" }
variable "SOURCE" { default = "https://github.com/BjoernSchotte/leonaid" }

group "default" { targets = ["core", "web", "pwa", "public", "proxy", "survey-validator"] }

target "_release" {
  platforms = ["linux/amd64"]
  labels = {
    "org.opencontainers.image.source" = SOURCE
    "org.opencontainers.image.revision" = REVISION
    "org.opencontainers.image.version" = VERSION
    "org.opencontainers.image.vendor" = "LeonAid"
  }
  attest = ["type=provenance,mode=max", "type=sbom"]
}

target "core" {
  inherits = ["_release"]
  context = "."
  dockerfile = "infra/compose/Dockerfile.core"
  tags = ["${REGISTRY}/core:${VERSION}"]
}

target "web" {
  inherits = ["_release"]
  context = "."
  dockerfile = "infra/compose/Dockerfile.web"
  tags = ["${REGISTRY}/web:${VERSION}"]
}

target "pwa" {
  inherits = ["_release"]
  context = "."
  dockerfile = "infra/compose/Dockerfile.pwa"
  tags = ["${REGISTRY}/pwa:${VERSION}"]
}

target "public" {
  inherits = ["_release"]
  context = "."
  dockerfile = "infra/compose/Dockerfile.public"
  tags = ["${REGISTRY}/public:${VERSION}"]
}

target "proxy" {
  inherits = ["_release"]
  context = "infra/proxy/image"
  dockerfile = "Dockerfile"
  tags = ["${REGISTRY}/proxy:${VERSION}"]
}

target "survey-validator" {
  inherits = ["_release"]
  context = "."
  dockerfile = "infra/compose/Dockerfile.survey-validator"
  tags = ["${REGISTRY}/survey-validator:${VERSION}"]
}
