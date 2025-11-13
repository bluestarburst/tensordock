#!/bin/bash
# Build and push TensorDock DigitalOcean Docker image
# This script builds a CPU-only Docker image based on Ubuntu 22.04 with all dependencies pre-baked
# Supports building from macOS using Docker buildx for cross-platform builds

set -euo pipefail

# Configuration
IMAGE_NAME="${IMAGE_NAME:-bluestarburst/tensordock-do}"
VERSION="${VERSION:-latest}"
DOCKERFILE="${DOCKERFILE:-Dockerfile.digitalocean}"
BUILD_CONTEXT="${BUILD_CONTEXT:-..}"
PLATFORM="${PLATFORM:-linux/amd64}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $*"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $*"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $*" >&2
}

# Check if Docker is available
if ! command -v docker >/dev/null 2>&1; then
    error "Docker is not installed or not in PATH"
    exit 1
fi

# Check if buildx is available
if ! docker buildx version >/dev/null 2>&1; then
    warn "Docker buildx is not available. Attempting to use regular docker build..."
    USE_BUILDX=false
else
    USE_BUILDX=true
    log "Docker buildx is available"
fi

# Setup buildx builder for cross-platform builds (macOS → Linux)
if [ "$USE_BUILDX" = true ]; then
    log "Setting up buildx builder..."
    
    # Check if builder exists
    if ! docker buildx ls | grep -q "multiarch"; then
        log "Creating new buildx builder 'multiarch'..."
        docker buildx create --name multiarch --use --bootstrap || {
            warn "Failed to create buildx builder, using default"
            docker buildx use default || true
        }
    else
        log "Using existing buildx builder 'multiarch'..."
        docker buildx use multiarch || {
            warn "Failed to use multiarch builder, using default"
            docker buildx use default || true
        }
    fi
    
    # Inspect builder to ensure it's ready
    docker buildx inspect --bootstrap || {
        warn "Failed to bootstrap builder, continuing anyway..."
    }
fi

# Get git commit hash for versioning (optional)
GIT_COMMIT=""
if command -v git >/dev/null 2>&1 && [ -d "$BUILD_CONTEXT/.git" ]; then
    GIT_COMMIT=$(cd "$BUILD_CONTEXT" && git rev-parse --short HEAD 2>/dev/null || echo "")
    if [ -n "$GIT_COMMIT" ]; then
        log "Git commit: $GIT_COMMIT"
    fi
fi

# Build arguments
BUILD_ARGS=""
if [ -n "$GIT_COMMIT" ]; then
    BUILD_ARGS="--build-arg GIT_COMMIT=$GIT_COMMIT"
fi

# Determine if we should push
PUSH="${PUSH:-false}"
if [ "$PUSH" = "true" ] || [ "$PUSH" = "1" ]; then
    PUSH_IMAGE=true
    log "Will push image to registry after build"
else
    PUSH_IMAGE=false
    log "Will NOT push image (set PUSH=true to push)"
fi

# Build the image
log "Building Docker image: $IMAGE_NAME:$VERSION"
log "Platform: $PLATFORM"
log "Dockerfile: $DOCKERFILE"
log "Build context: $BUILD_CONTEXT"

cd "$(dirname "$0")"

if [ "$USE_BUILDX" = true ]; then
    # Use buildx for cross-platform builds
    BUILD_CMD="docker buildx build"
    BUILD_CMD="$BUILD_CMD --platform $PLATFORM"
    BUILD_CMD="$BUILD_CMD -f $DOCKERFILE"
    BUILD_CMD="$BUILD_CMD -t $IMAGE_NAME:$VERSION"
    
    if [ -n "$GIT_COMMIT" ]; then
        BUILD_CMD="$BUILD_CMD -t $IMAGE_NAME:$GIT_COMMIT"
    fi
    
    if [ "$PUSH_IMAGE" = true ]; then
        BUILD_CMD="$BUILD_CMD --push"
        log "Building and pushing image..."
    else
        BUILD_CMD="$BUILD_CMD --load"
        warn "Note: --load only works for native platform. For cross-platform builds, use --push"
    fi
    
    BUILD_CMD="$BUILD_CMD $BUILD_ARGS"
    BUILD_CMD="$BUILD_CMD $BUILD_CONTEXT"
    
    log "Executing: $BUILD_CMD"
    eval "$BUILD_CMD"
else
    # Fallback to regular docker build
    warn "Using regular docker build (not cross-platform)"
    docker build \
        -f "$DOCKERFILE" \
        -t "$IMAGE_NAME:$VERSION" \
        $BUILD_ARGS \
        "$BUILD_CONTEXT"
    
    if [ "$PUSH_IMAGE" = true ]; then
        log "Pushing image to registry..."
        docker push "$IMAGE_NAME:$VERSION"
        if [ -n "$GIT_COMMIT" ]; then
            docker tag "$IMAGE_NAME:$VERSION" "$IMAGE_NAME:$GIT_COMMIT"
            docker push "$IMAGE_NAME:$GIT_COMMIT"
        fi
    fi
fi

if [ $? -eq 0 ]; then
    log "Build completed successfully!"
    log "Image: $IMAGE_NAME:$VERSION"
    if [ -n "$GIT_COMMIT" ]; then
        log "Also tagged as: $IMAGE_NAME:$GIT_COMMIT"
    fi
    
    if [ "$PUSH_IMAGE" = false ]; then
        log ""
        log "To push the image, run:"
        log "  docker push $IMAGE_NAME:$VERSION"
        if [ -n "$GIT_COMMIT" ]; then
            log "  docker push $IMAGE_NAME:$GIT_COMMIT"
        fi
        log ""
        log "Or set PUSH=true and rebuild:"
        log "  PUSH=true $0"
    fi
else
    error "Build failed!"
    exit 1
fi

