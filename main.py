from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, HttpUrl
from playwright.async_api import async_playwright
import asyncio
import os
import uuid
from typing import Optional
import tempfile
from pathlib import Path

app = FastAPI(
    title="Web Screenshot API",
    description="API to capture screenshots of web pages using Playwright",
    version="1.0.0"
)

class ScreenshotRequest(BaseModel):
    url: HttpUrl
    width: Optional[int] = 1920
    height: Optional[int] = 1080
    full_page: Optional[bool] = False
    format: Optional[str] = "png"
    quality: Optional[int] = 80
    timeout: Optional[int] = 30000

class ScreenshotResponse(BaseModel):
    success: bool
    filename: str
    message: str

TEMP_DIR = Path(tempfile.gettempdir()) / "screenshots"
TEMP_DIR.mkdir(exist_ok=True)

@app.get("/")
async def root():
    return {
        "message": "Web Screenshot API",
        "endpoints": {
            "POST /screenshot": "Take a screenshot of a web page",
            "GET /screenshot": "Take a screenshot via query parameters",
            "GET /health": "Health check"
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "screenshot-api"}

async def capture_screenshot(
    url: str,
    width: int = 1920,
    height: int = 1080,
    full_page: bool = False,
    format: str = "png",
    quality: int = 80,
    timeout: int = 30000
) -> str:
    file_extension = "png" if format == "png" else "jpg"
    filename = f"screenshot_{uuid.uuid4().hex}.{file_extension}"
    filepath = TEMP_DIR / filename
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        
        try:
            # Create context and page
            context = await browser.new_context(
                viewport={'width': width, 'height': height},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            )
            page = await context.new_page()
            
            # Set timeout
            page.set_default_timeout(timeout)
            
            # Navigate to URL
            await page.goto(url, wait_until='networkidle')
            
            # Wait a bit for dynamic content
            await asyncio.sleep(2)
            
            # Take screenshot
            screenshot_options = {
                'path': str(filepath),
                'full_page': full_page
            }
            
            if format == "jpeg":
                screenshot_options['type'] = 'jpeg'
                screenshot_options['quality'] = quality
            else:
                screenshot_options['type'] = 'png'
            
            await page.screenshot(**screenshot_options)
            
        finally:
            await browser.close()
    
    return filename

@app.post("/screenshot", response_model=ScreenshotResponse)
async def take_screenshot_post(request: ScreenshotRequest):
    try:
        # Validate format
        if request.format not in ["png", "jpeg", "jpg"]:
            raise HTTPException(status_code=400, detail="Format must be 'png' or 'jpeg'")
        
        # Normalize format
        format_normalized = "png" if request.format == "png" else "jpeg"
        
        # Validate quality for jpeg
        if format_normalized == "jpeg" and (request.quality < 1 or request.quality > 100):
            raise HTTPException(status_code=400, detail="Quality must be between 1 and 100 for JPEG")
        
        # Validate dimensions
        if request.width < 100 or request.width > 3840:
            raise HTTPException(status_code=400, detail="Width must be between 100 and 3840")
        
        if request.height < 100 or request.height > 2160:
            raise HTTPException(status_code=400, detail="Height must be between 100 and 2160")
        
        filename = await capture_screenshot(
            url=str(request.url),
            width=request.width,
            height=request.height,
            full_page=request.full_page,
            format=format_normalized,
            quality=request.quality,
            timeout=request.timeout
        )
        
        return ScreenshotResponse(
            success=True,
            filename=filename,
            message="Screenshot captured successfully"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to capture screenshot: {str(e)}")

@app.get("/screenshot")
async def take_screenshot_get(
    url: str = Query(..., description="URL of the web page to capture"),
    width: int = Query(1920, ge=100, le=3840, description="Viewport width"),
    height: int = Query(1080, ge=100, le=2160, description="Viewport height"),
    full_page: bool = Query(False, description="Capture full page or just viewport"),
    format: str = Query("png", regex="^(png|jpeg|jpg)$", description="Image format"),
    quality: int = Query(80, ge=1, le=100, description="JPEG quality (1-100)"),
    timeout: int = Query(30000, ge=5000, le=120000, description="Timeout in milliseconds")
):

    try:
        # Validate URL format
        if not url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
        
        # Normalize format
        format_normalized = "png" if format == "png" else "jpeg"
        
        filename = await capture_screenshot(
            url=url,
            width=width,
            height=height,
            full_page=full_page,
            format=format_normalized,
            quality=quality,
            timeout=timeout
        )
        
        return JSONResponse(content={
            "success": True,
            "filename": filename,
            "message": "Screenshot captured successfully",
            "download_url": f"/download/{filename}"
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to capture screenshot: {str(e)}")

@app.get("/download/{filename}")
async def download_screenshot(filename: str):
    filepath = TEMP_DIR / filename
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    
    # Determine media type
    if filename.endswith('.png'):
        media_type = 'image/png'
    else:
        media_type = 'image/jpeg'
    
    return FileResponse(
        path=str(filepath),
        media_type=media_type,
        filename=filename
    )

@app.delete("/screenshot/{filename}")
async def delete_screenshot(filename: str):
    filepath = TEMP_DIR / filename
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    
    try:
        os.remove(filepath)
        return {"success": True, "message": f"Screenshot {filename} deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete screenshot: {str(e)}")

@app.get("/list")
async def list_screenshots():
    try:
        screenshots = []
        for file in TEMP_DIR.glob("screenshot_*"):
            if file.is_file():
                screenshots.append({
                    "filename": file.name,
                    "size": file.stat().st_size,
                    "created": file.stat().st_ctime
                })
        
        return {
            "success": True,
            "count": len(screenshots),
            "screenshots": screenshots
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list screenshots: {str(e)}")

@app.on_event("startup")
async def startup_event():
    print(f"Screenshot API started. Screenshots will be saved to: {TEMP_DIR}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)