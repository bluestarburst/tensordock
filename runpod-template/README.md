# RunPod Template for TensorDock

This directory contains files to build a RunPod template that works with our TensorDock system.

## Option A: Using RunPod Template (Recommended for Production)

### Building the Template

1. **Build and Push the Docker image:**
   ```bash
   cd tensordock/runpod-template
   
   # Using helper script (recommended)
   ./build-and-push.sh bluestarburst latest
   docker push bluestarburst/tensordock-runpod-template:latest
   
   # Or manually
   docker build -t bluestarburst/tensordock-runpod-template:latest .
   docker push bluestarburst/tensordock-runpod-template:latest
   ```
   
   **Note:** Replace `bluestarburst` with your Docker Hub username. 
   Docker Hub format: `docker.io/username/imagename` (or just `username/imagename`)

2. **Create RunPod Template:**
   - Go to [RunPod Dashboard](https://www.runpod.io/console/templates)
   - Click "Create Template"
   - Set image name: `bluestarburst/tensordock-runpod-template:latest`
   - Configure default settings (GPU type, memory, etc.)
   - Save the template and note the Template ID

4. **Configure in Firestore:**
   ```typescript
   // In admin/image document
   {
     runpodTemplateId: "your-template-id-here"
   }
   ```

### How It Works

1. RunPod creates a pod from your template
2. The template's `start.sh` script runs on startup
3. It receives `STARTUP_SCRIPT` environment variable from our provider
4. The script writes and executes the startup script
5. The startup script installs Docker (if needed), sets up control plane, etc.

### Advantages

- ✅ Faster startup (Docker pre-installed)
- ✅ Consistent environment
- ✅ Easier to debug (template is versioned)
- ✅ Can pre-configure optimizations

## Option B: Using Custom Image (Current Default)

If no `runpodTemplateId` is set, the provider uses a base image and passes the startup script directly.

### How It Works

1. Provider generates startup script using `userDataStartupScript()`
2. Creates pod with base image: `runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04`
3. Passes startup script via `STARTUP_SCRIPT` environment variable
4. The base image should execute this script (may need custom entrypoint)

### Advantages

- ✅ No template setup required
- ✅ Always uses latest startup script logic
- ✅ More flexible (can change script without rebuilding template)

### Limitations

- ⚠️ Requires base image to support `STARTUP_SCRIPT` execution
- ⚠️ May be slower (Docker installation happens at runtime)
- ⚠️ Less consistent (depends on base image state)

## Recommendation

**For Production:** Use Option A (Template) for faster, more reliable startup
**For Development:** Use Option B (Custom Image) for easier iteration

## Testing the Template Locally

```bash
# Build locally
docker build -t tensordock-runpod-test .

# Test with environment variables
docker run -it \
  -e STARTUP_SCRIPT="$(cat /path/to/generated/script.sh)" \
  -e USER_ID="test-user" \
  -e RESOURCE_TYPE="gpu" \
  tensordock-runpod-test
```

## Troubleshooting

**Template not executing startup script:**
- Verify `STARTUP_SCRIPT` env var is being passed
- Check template's entrypoint/CMD configuration
- Review pod logs in RunPod dashboard

**Docker not available in template:**
- Ensure Docker is installed in the template image
- Verify Docker daemon starts correctly
- Check `/var/run/docker.sock` permissions

