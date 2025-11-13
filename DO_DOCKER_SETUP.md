# DigitalOcean Docker Container Setup Guide

This guide explains how to build, deploy, and maintain the TensorDock Docker image for DigitalOcean. Using Docker containers eliminates snapshot storage costs while maintaining fast startup times (30-60 seconds).

## Overview

The Docker approach uses:
- **DigitalOcean Docker 1-Click App**: Pre-configured droplet with Docker installed
- **Pre-built Docker Image**: CPU-only image with all dependencies pre-installed
- **Fast Startup**: Container starts in 30-60 seconds (vs 5-10 minutes with full installation)

The Docker image includes:
- Ubuntu 22.04 base (CPU-only, no PyTorch/CUDA)
- All system packages (Python, build tools, FFmpeg libraries, coturn, supervisor)
- All Python dependencies from `requirements.txt` (111 packages including Jupyter, aiortc, etc.)
- Pre-configured users (appuser, watcher)
- TensorDock application code

## Prerequisites

1. **Docker**: Installed locally for building images
2. **Docker Hub Account** (or DigitalOcean Container Registry): For storing images
3. **DigitalOcean API Token**: For creating droplets

## Building the Docker Image

### Method 1: Automated Script (Recommended)

The `build-do-docker.sh` script automates the build and push process:

```bash
cd tensordock

# Build only (local)
./build-do-docker.sh

# Build and push to Docker Hub
PUSH=true ./build-do-docker.sh
```

**Custom Configuration:**
```bash
IMAGE_NAME="your-username/tensordock-do" \
VERSION="v1.0.0" \
PUSH=true \
./build-do-docker.sh
```

**What the script does:**
1. Sets up Docker buildx for cross-platform builds (macOS → Linux)
2. Builds the Docker image from `Dockerfile.digitalocean`
3. Tags the image with version and git commit hash
4. Optionally pushes to Docker Hub

**Expected time:** 10-20 minutes (depending on network speed for package downloads)

### Method 2: Manual Build

```bash
cd tensordock

# Build the image
docker build \
  -f Dockerfile.digitalocean \
  -t bluestarburst/tensordock-do:latest \
  ..

# Push to registry
docker push bluestarburst/tensordock-do:latest
```

## Image Details

**Base Image**: `ubuntu:22.04`
**Size**: ~1-2GB (much smaller than Vast AI image which includes PyTorch/CUDA)
**Architecture**: `linux/amd64`
**Ports Exposed**:
- `8888/tcp` - Jupyter server
- `8765/tcp` - Python WebRTC server
- `50000/udp` - TURN server

## Using the Docker Image

### 1. Update Firestore Configuration

In Firestore, update the `admin/image` document:

```json
{
  "doDockerImage": "bluestarburst/tensordock-do:latest",
  "doDockerStartupScriptUrl": "https://raw.githubusercontent.com/bluestarburst/tensorboard/refs/heads/main/tensordock/do-docker-startup.sh",
  "doImage": "docker-22-04"
}
```

**Configuration Options:**
- `doDockerImage`: Docker image name (default: `bluestarburst/tensordock-do:latest`)
- `doDockerStartupScriptUrl`: URL to Docker startup script (default: GitHub raw URL)
- `doImage`: DigitalOcean base image (default: `docker-22-04`, options: `docker-20-04`, `docker-22-04`)

### 2. How It Works

1. **Droplet Creation**: DigitalOcean creates a droplet from Docker 1-Click App image
2. **Bootstrap Script**: Cloud-init runs bootstrap script that sets environment variables
3. **Docker Startup**: Bootstrap downloads and executes `do-docker-startup.sh`
4. **Container Launch**: Startup script pulls Docker image and runs container with proper port mappings
5. **Services Start**: Container runs supervisord which starts Jupyter, Python server, and TURN server

### 3. Verify Deployment

After creating a droplet:
1. **Check container status**: `docker ps` (should show `tensordock-container`)
2. **Check logs**: `docker logs tensordock-container`
3. **Verify services**: 
   - Jupyter: `curl http://localhost:8888`
   - Python server: `curl http://localhost:8765`
   - TURN server: Check supervisor logs

## Updating the Image

### When to Rebuild

Rebuild the image when:
- Python dependencies change (`requirements.txt`)
- System packages need updates
- TensorDock code structure changes significantly
- Ubuntu base image needs security updates

### When NOT to Rebuild

You don't need to rebuild for:
- Code changes (handled by GitHub pull in container startup, if enabled)
- Configuration changes (handled by runtime environment variables)
- Minor bug fixes

### Update Process

1. **Update dependencies** in `requirements.txt` or `Dockerfile.digitalocean`
2. **Rebuild image** using `build-do-docker.sh`
3. **Push to registry** with `PUSH=true`
4. **Update Firestore** with new image tag (if using versioned tags)
5. **Test** with a new droplet

## Troubleshooting

### Build Issues

**Issue**: Build fails with "Python.h: No such file or directory"
- **Solution**: Ensure `python3-dev` is installed in Dockerfile (already included)

**Issue**: Build fails with pip conflicts
- **Solution**: Dockerfile uses `--break-system-packages` for Python 3.12+ or `--ignore-installed` for older versions

**Issue**: Cross-platform build fails on macOS
- **Solution**: Ensure Docker buildx is installed and builder is set up correctly

### Deployment Issues

**Issue**: Container fails to start
- **Solution**: Check Docker logs: `docker logs tensordock-container`
- **Solution**: Verify image exists: `docker images | grep tensordock-do`
- **Solution**: Check firewall rules: `ufw status`

**Issue**: Ports not accessible
- **Solution**: Verify UFW is enabled and ports are allowed
- **Solution**: Check DigitalOcean Cloud Firewall settings
- **Solution**: Verify port mappings in `docker run` command

**Issue**: Services don't start inside container
- **Solution**: Check supervisor logs: `docker exec tensordock-container supervisorctl status`
- **Solution**: Verify environment variables are set correctly
- **Solution**: Check file permissions (appuser/watcher users)

### Performance Issues

**Issue**: Startup still takes too long
- **Solution**: Verify Docker image is being pulled (not built from scratch)
- **Solution**: Check network speed during image pull
- **Solution**: Ensure image is cached locally if possible

## Cost Comparison

### Docker Approach (Current)
- **Docker image storage**: Free on Docker Hub (public), ~$0.02/GB/month on DigitalOcean Container Registry
- **Droplet storage**: Only droplet disk space (~$0.10/GB/month)
- **Total**: ~$0.10-0.20/month per image version

### Custom Image Approach (Previous)
- **Snapshot storage**: ~$0.05/GB/month (typically 2-5 GB per snapshot)
- **Droplet storage**: Same as Docker approach
- **Total**: ~$0.20-0.50/month per snapshot

**Savings**: ~50-70% reduction in storage costs

## Best Practices

1. **Version your images**: Use tags like `v1.0.0`, `latest`, or git commit hashes
2. **Keep old images**: Don't delete old images immediately - keep for rollback
3. **Test before production**: Always test new images with a test droplet first
4. **Monitor image size**: Keep images under 2GB for faster pulls
5. **Use multi-stage builds**: Consider if image size becomes an issue (not currently needed)

## Comparison: Docker vs Custom Image

| Aspect | Custom Image (Previous) | Docker (Current) |
|--------|------------------------|------------------|
| Storage cost | ~$0.05/GB/month | Free (Docker Hub) or ~$0.02/GB/month |
| Startup time | 30-60 seconds | 30-60 seconds |
| Image size | 2-5 GB | 1-2 GB |
| Build complexity | High (droplet + snapshot) | Low (Docker build) |
| Update process | Rebuild droplet | Rebuild Docker image |
| Portability | DigitalOcean only | Any Docker host |

## Related Files

- `Dockerfile.digitalocean` - CPU-only Docker image definition
- `do-docker-startup.sh` - Docker container startup script
- `build-do-docker.sh` - Build and push script
- `functions/src/services/cloud-providers/digitalocean-provider.ts` - Provider implementation

## Support

For issues or questions:
1. Check container logs: `docker logs tensordock-container`
2. Check supervisor logs: `docker exec tensordock-container supervisorctl tail -f all`
3. Check cloud-init logs: `/var/log/cloud-init-output.log`
4. Review DigitalOcean API documentation: https://docs.digitalocean.com/reference/api/api-reference/

