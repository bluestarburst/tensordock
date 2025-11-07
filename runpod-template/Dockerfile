# RunPod Template Dockerfile for TensorDock
# This creates a template image that can be used with RunPod
# The template will execute the startup script passed via STARTUP_SCRIPT env var

FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

# Install Docker (needed for control plane to manage user containers)
# RunPod base images may already have Docker, but we ensure it's available
RUN if ! command -v docker >/dev/null 2>&1; then \
        curl -fsSL https://get.docker.com -o get-docker.sh && \
        sh get-docker.sh && \
        rm get-docker.sh; \
    else \
        echo "Docker already installed: $(docker --version)"; \
    fi

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    ca-certificates \
    ufw \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Ensure Docker daemon can start (if not using host's Docker)
# Note: RunPod may provide Docker socket, so we don't necessarily need to start daemon
RUN if [ ! -S /var/run/docker.sock ]; then \
        echo "Docker socket not found, daemon will need to be started"; \
    else \
        echo "Docker socket found at /var/run/docker.sock"; \
    fi

# Copy startup script
COPY start.sh /usr/local/bin/tensordock-start.sh
RUN chmod +x /usr/local/bin/tensordock-start.sh

# Set entrypoint to run the startup script
ENTRYPOINT ["/usr/local/bin/tensordock-start.sh"]

# Default command (can be overridden by RunPod)
CMD []

# Health check (optional - can be used by RunPod)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD pgrep -f "tensordock-control-plane" || exit 1

