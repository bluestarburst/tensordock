#!/bin/bash
# Build and push script for RunPod template
# Usage: ./build-and-push.sh [dockerhub-username] [tag]
#
# Examples:
#   ./build-and-push.sh bluestarburst latest
#   ./build-and-push.sh myusername v1.0.0
#   ./build-and-push.sh  # Uses bluestarburst/latest by default

set -e

# Docker Hub username (defaults to bluestarburst based on codebase)
DOCKERHUB_USER="${1:-bluestarburst}"
TAG="${2:-latest}"
IMAGE_NAME="${DOCKERHUB_USER}/tensordock-runpod-template:${TAG}"

echo "=========================================="
echo "Building RunPod Template Image"
echo "=========================================="
echo "Docker Hub Username: ${DOCKERHUB_USER}"
echo "Tag: ${TAG}"
echo "Image Name: ${IMAGE_NAME}"
echo ""

# Check if logged into Docker Hub
if ! docker info | grep -q "Username:"; then
    echo "⚠️  WARNING: Not logged into Docker Hub"
    echo "   Run: docker login"
    echo ""
fi

# Build the image
echo "Building image..."
docker build -t "${IMAGE_NAME}" .

echo ""
echo "✅ Build complete!"
echo ""
echo "Image: ${IMAGE_NAME}"
echo ""
echo "To push to Docker Hub:"
echo "  1. Make sure you're logged in: docker login"
echo "  2. Push the image: docker push ${IMAGE_NAME}"
echo ""
echo "Then:"
echo "  1. Go to RunPod Dashboard → Templates → Create Template"
echo "  2. Set image name: ${IMAGE_NAME}"
echo "  3. Configure GPU type, memory, etc."
echo "  4. Save and copy the Template ID"
echo "  5. Set runpodTemplateId in Firestore admin/image document"
echo ""

