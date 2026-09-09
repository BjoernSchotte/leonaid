// Immutable source inputs determine BuildKit hits; scopes stay stable across commits.
variable "CACHE_NAMESPACE" { default = "leonaid-build-v1" }
variable "CACHE_WRITE" { default = "false" }
variable "CACHE_READ" { default = "true" }
group "default" { targets = ["api", "worker", "proxy", "web", "pwa", "public", "survey-validator"] }
group "survey-foundation" { targets = ["api", "survey-validator"] }
target "api" {
  context = "."
  dockerfile = "infra/compose/Dockerfile.core"
  platforms = ["linux/amd64"]
  tags = ["leonaid-cache-api:local"]
  cache-from = CACHE_READ == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-core-linux-amd64"] : []
  cache-to = CACHE_WRITE == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-core-linux-amd64,mode=max"] : []
}
target "worker" {
  context = "."
  dockerfile = "infra/compose/Dockerfile.core"
  platforms = ["linux/amd64"]
  tags = ["leonaid-cache-worker:local"]
  cache-from = CACHE_READ == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-core-linux-amd64"] : []
  cache-to = []
}
target "proxy" {
  context = "infra/proxy/image"
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]
  tags = ["leonaid-cache-proxy:local"]
  cache-from = CACHE_READ == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-proxy-linux-amd64"] : []
  cache-to = CACHE_WRITE == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-proxy-linux-amd64,mode=max"] : []
}
target "web" {
  context = "."
  dockerfile = "infra/compose/Dockerfile.web"
  platforms = ["linux/amd64"]
  tags = ["leonaid-cache-web:local"]
  cache-from = CACHE_READ == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-web-linux-amd64"] : []
  cache-to = CACHE_WRITE == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-web-linux-amd64,mode=max"] : []
}
target "pwa" {
  context = "."
  dockerfile = "infra/compose/Dockerfile.pwa"
  platforms = ["linux/amd64"]
  tags = ["leonaid-cache-pwa:local"]
  cache-from = CACHE_READ == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-pwa-linux-amd64"] : []
  cache-to = CACHE_WRITE == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-pwa-linux-amd64,mode=max"] : []
}
target "public" {
  context = "."
  dockerfile = "infra/compose/Dockerfile.public"
  platforms = ["linux/amd64"]
  tags = ["leonaid-cache-public:local"]
  cache-from = CACHE_READ == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-public-linux-amd64"] : []
  cache-to = CACHE_WRITE == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-public-linux-amd64,mode=max"] : []
}
target "survey-validator" {
  context = "."
  dockerfile = "infra/compose/Dockerfile.survey-validator"
  platforms = ["linux/amd64"]
  tags = ["leonaid-cache-survey-validator:local"]
  cache-from = CACHE_READ == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-survey-validator-linux-amd64"] : []
  cache-to = CACHE_WRITE == "true" ? ["type=gha,version=2,scope=${CACHE_NAMESPACE}-survey-validator-linux-amd64,mode=max"] : []
}
