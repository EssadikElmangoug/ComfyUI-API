# ComfyUI API Documentation

## Base URL
```
http://localhost:5000
```

## 1. Flux Text-to-Image
Generate images using the Flux model.

**Endpoint:** `/api/flux-text-to-image`  
**Method:** `POST`  
**Content-Type:** `application/json`

### Request Parameters
```json
{
    "prompt": "string",           // Required: Text description of the image to generate
    "negative_prompt": "string",  // Optional: Text description of what to avoid in the image
    "width": number,             // Optional: Width of the generated image (default: 1024)
    "height": number            // Optional: Height of the generated image (default: 1024)
}
```

### Response
```json
{
    "process_id": "string",  // ID to track the generation process
    "status": "queued"      // Initial status of the generation
}
```

### Example
```bash
curl -X POST http://localhost:5000/api/flux-text-to-image \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "cute anime girl with fluffy ears",
    "negative_prompt": "blurry, low quality",
    "width": 1024,
    "height": 768
  }'
```

## 2. Wan Image-to-Video
Generate videos from an image using the Wan model.

**Endpoint:** `/api/wan-image-to-video`  
**Method:** `POST`  
**Content-Type:** `multipart/form-data`

### Request Parameters
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| image | file | Yes | Input image file (PNG, JPG). The file will be saved in ComfyUI's input directory. |
| prompt | string | No | Text description to guide the video generation |
| width | number | No | Width of the generated video (default: 512) |
| height | number | No | Height of the generated video (default: 512) |
| video_length | number | No | Length of the video in seconds (default: 4) |

### Response
```json
{
    "process_id": "string",  // ID to track the generation process
    "status": "queued"      // Initial status of the generation
}
```

### Example
```bash
# Using curl
curl -X POST http://localhost:5000/api/wan-image-to-video \
  -F "image=@/path/to/your/image.png" \
  -F "prompt=cinematic slow motion scene" \
  -F "width=768" \
  -F "height=432" \
  -F "video_length=6"

# Using Python requests
import requests

url = "http://localhost:5000/api/wan-image-to-video"
files = {
    'image': ('image.png', open('path/to/your/image.png', 'rb'), 'image/png')
}
data = {
    'prompt': 'cinematic slow motion scene',
    'width': 768,
    'height': 432,
    'video_length': 6
}

response = requests.post(url, files=files, data=data)
print(response.json())
```

## 3. Wan Text-to-Video
Generate videos from text using the Wan model.

**Endpoint:** `/api/wan-text-to-video`  
**Method:** `POST`  
**Content-Type:** `application/json`

### Request Parameters
```json
{
    "prompt": "string",           // Required: Text description of the video to generate
    "negative_prompt": "string",  // Optional: Text description of what to avoid in the video
    "width": number,             // Optional: Width of the generated video (default: 512)
    "height": number,            // Optional: Height of the generated video (default: 512)
    "video_length": number       // Optional: Length of the video in seconds (default: 4)
}
```

### Response
```json
{
    "process_id": "string",  // ID to track the generation process
    "status": "queued"      // Initial status of the generation
}
```

### Example
```bash
curl -X POST http://localhost:5000/api/wan-text-to-video \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "cinematic scene of a sunset",
    "negative_prompt": "blurry, low quality",
    "width": 768,
    "height": 432,
    "video_length": 6
  }'
```

## 4. FramePack Image-to-Video
Generate videos between two images using the FramePack model.

**Endpoint:** `/api/framepack-image-to-video`  
**Method:** `POST`  
**Content-Type:** `multipart/form-data`

### Request Parameters
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| start_image | file | Yes | First frame image file (PNG, JPG). Will be saved in ComfyUI's input directory. |
| end_image | file | Yes | Last frame image file (PNG, JPG). Will be saved in ComfyUI's input directory. |
| prompt | string | No | Text description to guide the video generation |

### Response
```json
{
    "process_id": "string",  // ID to track the generation process
    "status": "queued"      // Initial status of the generation
}
```

### Example
```bash
curl -X POST http://localhost:5000/api/framepack-image-to-video \
  -F "start_image=@first_frame.png" \
  -F "end_image=@last_frame.png" \
  -F "prompt=smooth transition between scenes"
```

## Check Generation Status
To check the status of your generation, use the status endpoint:

```bash
curl -X GET http://localhost:5000/api/status/{process_id}
```

The status endpoint will return either:
```json
{
    "process_id": "string",
    "status": "queued"
}
```

Or when completed:
```json
{
    "process_id": "string",
    "status": "success",
    "file_name": "string"  // Name of the generated file
}
```

## Download Generated Files
To download generated files, use the download endpoint:

```bash
curl -X GET http://localhost:5000/api/download/{filename}
```

## Error Responses
All endpoints may return the following error responses:

### 400 Bad Request
```json
{
    "error": "Missing required parameters"
}
```

### 500 Internal Server Error
```json
{
    "error": "Error message describing what went wrong"
}
```

## Notes
1. All generated media (images/videos) are saved in ComfyUI's output directory
2. Input files are saved in ComfyUI's input directory
3. The API uses the ComfyUI server at `https://r9mu8pq2ipcfw9-8188.proxy.runpod.net/`
4. Processing time may vary depending on the complexity of the request and server load
5. Files are automatically cleaned up in case of errors during processing 