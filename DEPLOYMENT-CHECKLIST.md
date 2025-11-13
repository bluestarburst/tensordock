# Deployment Checklist for VastAI Custom Docker Image

This checklist covers all the steps needed to deploy the optimized VastAI Docker image implementation.

## ✅ Code Changes (Already Complete)

- [x] Created `Dockerfile.vastai` with pre-baked dependencies
- [x] Created `vastai-onstart-minimal.sh` for runtime configuration
- [x] Created `build-vastai-image.sh` for building and pushing images
- [x] Created `.dockerignore` to optimize build context
- [x] Updated `vastai-provider.ts` to use custom image by default
- [x] Fixed PyTorch base image tag (using specific version instead of `@vastai-automatic-tag`)
- [x] Fixed user creation to handle existing users in base image

## 🔨 Build and Push Docker Image

### Step 1: Build the Image

```bash
cd tensordock
./build-vastai-image.sh
```

### Step 2: Push to Docker Hub (or your registry)

```bash
# Login to Docker Hub first
docker login

# Build and push
PUSH=true ./build-vastai-image.sh
```

**Important**: Make sure the image is publicly accessible or your VastAI instances can access it.

### Step 3: Verify Image

```bash
# Check image exists
docker images | grep tensordock-vastai

# Test pull (if public)
docker pull bluestarburst/tensordock-vastai:latest
```

## 🔧 Firebase Configuration

### Firestore Database Update

Update the `admin/image` document in Firestore with the new configuration fields:

**Path**: `admin/image`

**New Fields to Add** (all optional, defaults will be used if not set):

```json
{
  // ... existing fields ...
  
  // Custom Docker image configuration (OPTIONAL - defaults provided)
  "vastaiCustomImage": "bluestarburst/tensordock-vastai:latest",
  "vastaiUseCustomImage": true,
  "vastaiOnstartScriptUrl": "https://raw.githubusercontent.com/bluestarburst/tensordock/refs/heads/main/vastai-onstart-minimal.sh"
}
```

**Default Behavior** (if fields are not set):
- `vastaiUseCustomImage`: defaults to `true` (uses custom image)
- `vastaiCustomImage`: defaults to `"bluestarburst/tensordock-vastai:latest"`
- `vastaiOnstartScriptUrl`: defaults to minimal script URL for custom image, or full install script for PyTorch template

### Update ConfigData Interface (if needed)

The `ConfigData` interface in `functions/src/compute/instance-manager.ts` should include the new fields. Check if they're already there:

```typescript
interface ConfigData {
  // ... existing fields ...
  vastaiCustomImage?: string;
  vastaiUseCustomImage?: boolean;
  vastaiOnstartScriptUrl?: string;
}
```

**Note**: The provider's `ConfigData` interface already includes these fields. The instance-manager's interface may need updating if it doesn't pass through all config fields.

## 🔐 Secrets

**No new secrets required!** The existing secret is sufficient:

- ✅ `VAST_AI_API_KEY` - Already configured (used for VastAI API authentication)

## 📝 GitHub Repository

### Ensure Scripts are Accessible

The minimal onstart script must be accessible via raw GitHub URL:

```
https://raw.githubusercontent.com/bluestarburst/tensordock/refs/heads/main/vastai-onstart-minimal.sh
```

**Verify**:
1. Script exists in repository
2. Script is on the `main` branch (or update URL to correct branch)
3. Repository is public (or VastAI instances can access it)

## 🚀 Deployment Steps

### 1. Build and Push Image

```bash
cd tensordock
PUSH=true IMAGE_NAME=bluestarburst/tensordock-vastai VERSION=latest ./build-vastai-image.sh
```

### 2. Update Firestore Config (Optional)

If you want to customize the image or disable the custom image:

```javascript
// In Firebase Console or via script
const admin = require('firebase-admin');
const db = admin.firestore();

await db.collection('admin').doc('image').update({
  vastaiCustomImage: 'bluestarburst/tensordock-vastai:latest',
  vastaiUseCustomImage: true,
  vastaiOnstartScriptUrl: 'https://raw.githubusercontent.com/bluestarburst/tensordock/refs/heads/main/vastai-onstart-minimal.sh'
});
```

### 3. Deploy Firebase Functions

```bash
cd functions
npm run build
firebase deploy --only functions
```

### 4. Test Instance Creation

Create a test GPU instance and verify:
- Startup time is 30-60 seconds (vs 5-10+ minutes)
- All services start correctly (Jupyter, Python server, TURN, Monitor)
- Check logs to confirm custom image is being used

## 🔄 Rollback Plan

If you need to rollback to the old method:

**Option 1**: Set in Firestore config
```json
{
  "vastaiUseCustomImage": false
}
```

**Option 2**: Update default in code (temporary)
```typescript
const useCustomImage = false; // Force old method
```

## 📊 Monitoring

After deployment, monitor:

1. **Startup Times**: Should see 30-60 second startup vs 5-10+ minutes
2. **Instance Creation Success Rate**: Should remain the same or improve
3. **Error Logs**: Check for any image pull errors or startup failures
4. **Service Health**: Verify all services (Jupyter, Python server, etc.) start correctly

## 🐛 Troubleshooting

### Image Not Found
- Verify image is pushed to registry
- Check image name/tag matches config
- Ensure image is publicly accessible

### Startup Still Slow
- Check logs to see which image is being used
- Verify `vastaiUseCustomImage` is `true` in config
- Check if image is being pulled (may be slow first time)

### Services Not Starting
- Check supervisord logs
- Verify environment variables are set correctly
- Check if minimal script is accessible from GitHub

### Build Failures
- Verify PyTorch base image tag is correct (not `@vastai-automatic-tag`)
- Check Docker buildx is set up correctly
- Verify all files in build context are correct

## 📚 Additional Resources

- [VastAI Base Image Documentation](https://github.com/vast-ai/base-image)
- [A1111 Dockerfile Example](https://github.com/vast-ai/base-image/blob/main/derivatives/pytorch/derivatives/a1111/Dockerfile)
- [Docker Buildx Documentation](https://docs.docker.com/build/building/multi-platform/)

