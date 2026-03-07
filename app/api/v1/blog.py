"""
Blog API — posts, comments, likes, and cover generation.

Public endpoints for reading, commenting, and liking.
Authenticated endpoints (BLOG_SECRET_KEY) for publishing and moderation.
"""

import os
import re
import uuid
import time
import math
import httpx
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header, Request, Query
from pydantic import BaseModel, Field

from app.services.local_store import get_local_store
from app.dependencies import RateLimiter
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# ── Rate Limiters ──────────────────────────────────────────────────
_comment_hourly = RateLimiter(max_requests=5, window_seconds=3600)
_comment_per_post = RateLimiter(max_requests=1, window_seconds=120)
_like_hourly = RateLimiter(max_requests=50, window_seconds=3600)

# ── Cover directory detection ──────────────────────────────────────
def _get_covers_dir() -> Path:
    """Resolve blog covers directory (frontend public/blog/covers/)."""
    env_dir = os.getenv("BLOG_COVERS_DIR")
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # Production path
    prod = Path("/opt/dreamweaver-web/public/blog/covers")
    if prod.parent.parent.exists():
        prod.mkdir(parents=True, exist_ok=True)
        return prod

    # Dev path (relative to backend root)
    dev = Path(__file__).parent.parent.parent.parent / "dreamweaver-web" / "public" / "blog" / "covers"
    dev.mkdir(parents=True, exist_ok=True)
    return dev


# ── Pydantic Models ────────────────────────────────────────────────

class CoverImage(BaseModel):
    url: str = ""
    alt: str = ""
    fluxPrompt: str = ""

class SEO(BaseModel):
    metaTitle: str = ""
    metaDescription: str = ""
    ogImage: str = ""

class Engagement(BaseModel):
    likes: int = 0
    commentCount: int = 0

class CreatePostRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    subtitle: str = ""
    body: str = ""
    tags: List[str] = []
    status: str = "draft"  # "draft" or "published"
    author: str = "Dream Valley"
    seo: Optional[SEO] = None

class UpdatePostRequest(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    body: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None
    author: Optional[str] = None
    seo: Optional[SEO] = None

class CreateCommentRequest(BaseModel):
    displayName: str = Field(..., min_length=2, max_length=50)
    body: str = Field(..., min_length=10, max_length=2000)
    parentId: Optional[str] = None

class LikeAction(BaseModel):
    action: str = Field(..., pattern="^(like|unlike)$")


# ── Utility Functions ──────────────────────────────────────────────

def slugify(text: str) -> str:
    """Generate a URL-friendly slug from text."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')


def get_client_ip(request: Request) -> str:
    """Extract real client IP from behind nginx proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


def verify_blog_key(authorization: Optional[str] = Header(None)):
    """Verify Bearer token against BLOG_SECRET_KEY env var."""
    key = os.getenv("BLOG_SECRET_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="Blog secret key not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing or invalid")
    token = authorization.replace("Bearer ", "")
    if token != key:
        raise HTTPException(status_code=401, detail="Invalid blog key")


def _get_posts_collection():
    store = get_local_store()
    return store.collection("blog_posts")


def _get_comments_collection():
    store = get_local_store()
    return store.collection("blog_comments")


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _reading_time(text: str) -> int:
    return max(1, math.ceil(_word_count(text) / 200))


def _post_to_response(post: dict) -> dict:
    """Ensure post has all expected fields for API response."""
    return {
        "id": post.get("id", ""),
        "slug": post.get("slug", post.get("id", "")),
        "title": post.get("title", ""),
        "subtitle": post.get("subtitle", ""),
        "body": post.get("body", ""),
        "author": post.get("author", "Dream Valley"),
        "publishedAt": post.get("publishedAt"),
        "updatedAt": post.get("updatedAt"),
        "status": post.get("status", "draft"),
        "tags": post.get("tags", []),
        "coverImage": post.get("coverImage", {"url": "/blog/covers/default.webp", "alt": "", "fluxPrompt": ""}),
        "seo": post.get("seo", {"metaTitle": "", "metaDescription": "", "ogImage": ""}),
        "engagement": post.get("engagement", {"likes": 0, "commentCount": 0}),
        "readingTime": _reading_time(post.get("body", "")),
    }


# ── Public Endpoints ───────────────────────────────────────────────

@router.get("/posts")
async def list_posts(
    page: int = Query(1, ge=1),
    page_size: int = Query(9, ge=1, le=50),
    status_filter: str = Query("published", alias="status"),
):
    """Paginated list of blog posts. Returns published posts by default."""
    coll = _get_posts_collection()
    all_posts = coll.get()

    # Filter by status
    posts = [
        doc.to_dict() for doc in all_posts
        if doc.to_dict().get("status") == status_filter
    ]

    # Sort by publishedAt descending (newest first)
    posts.sort(
        key=lambda p: p.get("publishedAt", "1970-01-01T00:00:00Z"),
        reverse=True,
    )

    total = len(posts)
    total_pages = max(1, math.ceil(total / page_size))
    start = (page - 1) * page_size
    end = start + page_size
    page_posts = posts[start:end]

    return {
        "posts": [_post_to_response(p) for p in page_posts],
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
    }


@router.get("/posts/tag/{tag}")
async def list_posts_by_tag(
    tag: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(9, ge=1, le=50),
):
    """List published posts filtered by tag."""
    coll = _get_posts_collection()
    all_posts = coll.get()

    posts = [
        doc.to_dict() for doc in all_posts
        if doc.to_dict().get("status") == "published"
        and tag in doc.to_dict().get("tags", [])
    ]

    posts.sort(
        key=lambda p: p.get("publishedAt", "1970-01-01T00:00:00Z"),
        reverse=True,
    )

    total = len(posts)
    total_pages = max(1, math.ceil(total / page_size))
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "posts": [_post_to_response(p) for p in posts[start:end]],
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
        "tag": tag,
    }


@router.get("/posts/{slug}")
async def get_post(slug: str):
    """Get a single post with its comments."""
    coll = _get_posts_collection()
    doc = coll.document(slug).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Post not found")

    post = _post_to_response(doc.to_dict())

    # Load comments for this post
    comments_coll = _get_comments_collection()
    all_comments = comments_coll.get()
    post_comments = [
        c.to_dict() for c in all_comments
        if c.to_dict().get("postId") == slug
        and c.to_dict().get("status") == "visible"
    ]
    post_comments.sort(key=lambda c: c.get("createdAt", ""))

    post["comments"] = post_comments
    return post


@router.post("/posts/{slug}/like")
async def like_post(slug: str, body: LikeAction, request: Request):
    """Like or unlike a blog post."""
    ip = get_client_ip(request)
    if not _like_hourly.is_allowed(f"like:{ip}"):
        raise HTTPException(status_code=429, detail="Like rate limit exceeded (50/hour)")

    coll = _get_posts_collection()
    doc = coll.document(slug).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Post not found")

    post = doc.to_dict()
    engagement = post.get("engagement", {"likes": 0, "commentCount": 0})

    if body.action == "like":
        engagement["likes"] = engagement.get("likes", 0) + 1
    else:
        engagement["likes"] = max(0, engagement.get("likes", 0) - 1)

    coll.document(slug).update({"engagement": engagement})

    return {"likes": engagement["likes"]}


@router.post("/posts/{slug}/comments")
async def add_comment(slug: str, body: CreateCommentRequest, request: Request):
    """Add a comment to a blog post."""
    ip = get_client_ip(request)

    # Rate limit: 5 comments per IP per hour
    if not _comment_hourly.is_allowed(f"comment:{ip}"):
        raise HTTPException(status_code=429, detail="Comment rate limit exceeded (5/hour)")

    # Rate limit: 1 comment per IP per post per 2 minutes
    if not _comment_per_post.is_allowed(f"comment:{ip}:{slug}"):
        raise HTTPException(status_code=429, detail="Please wait 2 minutes before commenting on this post again")

    # Verify post exists
    posts_coll = _get_posts_collection()
    post_doc = posts_coll.document(slug).get()
    if not post_doc.exists:
        raise HTTPException(status_code=404, detail="Post not found")

    # Validate parentId if provided (must be existing comment on same post)
    if body.parentId:
        comments_coll = _get_comments_collection()
        parent_doc = comments_coll.document(body.parentId).get()
        if not parent_doc.exists:
            raise HTTPException(status_code=400, detail="Parent comment not found")
        parent = parent_doc.to_dict()
        if parent.get("postId") != slug:
            raise HTTPException(status_code=400, detail="Parent comment belongs to a different post")
        # No nested replies — parentId must be a top-level comment
        if parent.get("parentId"):
            raise HTTPException(status_code=400, detail="Replies cannot be replied to (one level only)")

    comment_id = str(uuid.uuid4())
    comment = {
        "id": comment_id,
        "postId": slug,
        "parentId": body.parentId,
        "displayName": body.displayName.strip(),
        "body": body.body.strip(),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "likes": 0,
        "status": "visible",
    }

    comments_coll = _get_comments_collection()
    comments_coll.add(comment)

    # Update post comment count
    post = post_doc.to_dict()
    engagement = post.get("engagement", {"likes": 0, "commentCount": 0})
    engagement["commentCount"] = engagement.get("commentCount", 0) + 1
    posts_coll.document(slug).update({"engagement": engagement})

    return comment


@router.post("/comments/{comment_id}/like")
async def like_comment(comment_id: str, body: LikeAction, request: Request):
    """Like or unlike a comment."""
    ip = get_client_ip(request)
    if not _like_hourly.is_allowed(f"clike:{ip}"):
        raise HTTPException(status_code=429, detail="Like rate limit exceeded (50/hour)")

    coll = _get_comments_collection()
    doc = coll.document(comment_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Comment not found")

    comment = doc.to_dict()
    if body.action == "like":
        comment["likes"] = comment.get("likes", 0) + 1
    else:
        comment["likes"] = max(0, comment.get("likes", 0) - 1)

    coll.document(comment_id).update({"likes": comment["likes"]})

    return {"likes": comment["likes"]}


# ── Authenticated Endpoints ────────────────────────────────────────

@router.post("/posts")
async def create_post(
    body: CreatePostRequest,
    authorization: Optional[str] = Header(None),
):
    """Create a new blog post. Requires BLOG_SECRET_KEY."""
    verify_blog_key(authorization)

    slug = slugify(body.title)
    if not slug:
        raise HTTPException(status_code=400, detail="Title must produce a valid slug")

    # Check slug uniqueness
    coll = _get_posts_collection()
    existing = coll.document(slug).get()
    if existing.exists:
        raise HTTPException(status_code=409, detail=f"A post with slug '{slug}' already exists")

    now = datetime.now(timezone.utc).isoformat()

    # Auto-populate SEO if not provided
    seo = body.seo.dict() if body.seo else {}
    if not seo.get("metaTitle"):
        seo["metaTitle"] = f"{body.title} | Dream Valley Blog"
    if not seo.get("metaDescription"):
        seo["metaDescription"] = body.body[:160].strip() if body.body else ""
    if not seo.get("ogImage"):
        seo["ogImage"] = f"/blog/covers/{slug}.webp"

    post = {
        "id": slug,
        "slug": slug,
        "title": body.title.strip(),
        "subtitle": body.subtitle.strip() if body.subtitle else "",
        "body": body.body,
        "author": body.author,
        "publishedAt": now if body.status == "published" else None,
        "updatedAt": None,
        "status": body.status,
        "tags": [t.strip().lower() for t in body.tags],
        "coverImage": {"url": f"/blog/covers/{slug}.webp", "alt": "", "fluxPrompt": ""},
        "seo": seo,
        "engagement": {"likes": 0, "commentCount": 0},
    }

    coll.add(post)
    logger.info("Blog post created: %s (status=%s)", slug, body.status)

    return _post_to_response(post)


@router.put("/posts/{slug}")
async def update_post(
    slug: str,
    body: UpdatePostRequest,
    authorization: Optional[str] = Header(None),
):
    """Update an existing blog post. Requires BLOG_SECRET_KEY."""
    verify_blog_key(authorization)

    coll = _get_posts_collection()
    doc = coll.document(slug).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Post not found")

    post = doc.to_dict()
    now = datetime.now(timezone.utc).isoformat()

    # Apply updates
    updates = {}
    if body.title is not None:
        updates["title"] = body.title.strip()
    if body.subtitle is not None:
        updates["subtitle"] = body.subtitle.strip()
    if body.body is not None:
        updates["body"] = body.body
    if body.tags is not None:
        updates["tags"] = [t.strip().lower() for t in body.tags]
    if body.author is not None:
        updates["author"] = body.author
    if body.status is not None:
        updates["status"] = body.status
        # Set publishedAt when first published
        if body.status == "published" and not post.get("publishedAt"):
            updates["publishedAt"] = now
    if body.seo is not None:
        updates["seo"] = body.seo.dict()

    updates["updatedAt"] = now

    coll.document(slug).update(updates)
    logger.info("Blog post updated: %s", slug)

    # Return updated post
    updated = coll.document(slug).get().to_dict()
    return _post_to_response(updated)


@router.delete("/posts/{slug}")
async def delete_post(
    slug: str,
    authorization: Optional[str] = Header(None),
):
    """Delete a blog post and its comments. Requires BLOG_SECRET_KEY."""
    verify_blog_key(authorization)

    coll = _get_posts_collection()
    doc = coll.document(slug).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Post not found")

    # Delete all comments for this post
    comments_coll = _get_comments_collection()
    all_comments = comments_coll.get()
    for c in all_comments:
        if c.to_dict().get("postId") == slug:
            comments_coll.document(c.id).delete()

    # Delete post
    coll.document(slug).delete()

    # Delete cover image if exists
    try:
        cover_path = _get_covers_dir() / f"{slug}.webp"
        if cover_path.exists():
            cover_path.unlink()
    except Exception:
        pass

    logger.info("Blog post deleted: %s", slug)
    return {"success": True, "slug": slug}


@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: str,
    authorization: Optional[str] = Header(None),
):
    """Delete a comment (moderation). Requires BLOG_SECRET_KEY."""
    verify_blog_key(authorization)

    coll = _get_comments_collection()
    doc = coll.document(comment_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Comment not found")

    comment = doc.to_dict()
    post_id = comment.get("postId")

    # Also delete any replies to this comment
    all_comments = coll.get()
    for c in all_comments:
        if c.to_dict().get("parentId") == comment_id:
            coll.document(c.id).delete()

    coll.document(comment_id).delete()

    # Update post comment count
    if post_id:
        posts_coll = _get_posts_collection()
        post_doc = posts_coll.document(post_id).get()
        if post_doc.exists:
            post = post_doc.to_dict()
            engagement = post.get("engagement", {"likes": 0, "commentCount": 0})
            # Recount comments to be accurate
            remaining = [
                c for c in coll.get()
                if c.to_dict().get("postId") == post_id
                and c.to_dict().get("status") == "visible"
            ]
            engagement["commentCount"] = len(remaining)
            posts_coll.document(post_id).update({"engagement": engagement})

    logger.info("Comment deleted: %s (post=%s)", comment_id, post_id)
    return {"success": True}


# ── Cover Generation ───────────────────────────────────────────────

COVER_PROMPT_TEMPLATE = """You are generating an image prompt for a blog post cover on a children's bedtime story app called Dream Valley.

Blog post title: {title}
Blog post opening: {opening}

Generate a Flux image prompt that:
- Captures the essence of the blog post's topic in a single dreamy scene
- Uses Dream Valley's visual style: warm palette, soft focus, dreamy watercolor/illustration quality, bedtime atmosphere
- Features warm amber/gold/purple tones (never harsh blue-white)
- Includes a child, sleeping creature, or cozy nighttime element if appropriate to the topic
- Is suitable for a 16:9 landscape header image
- Does NOT include any text, logos, or typography in the image

Respond with ONLY the Flux prompt. No explanation."""


async def _generate_flux_prompt(title: str, body: str) -> str:
    """Use Mistral AI to generate a FLUX image prompt from blog content."""
    api_key = os.getenv("MISTRAL_API_KEY", "")
    if not api_key:
        logger.warning("MISTRAL_API_KEY not set — using fallback prompt")
        return f"A dreamy watercolor illustration about {title}, warm amber and purple tones, cozy nighttime atmosphere, soft focus, bedtime scene, children's book style"

    # Extract first 500 words
    words = body.split()[:500]
    opening = " ".join(words)

    prompt = COVER_PROMPT_TEMPLATE.format(title=title, opening=opening)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mistral-large-latest",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 300,
                    "temperature": 0.8,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            flux_prompt = data["choices"][0]["message"]["content"].strip()
            logger.info("Generated FLUX prompt: %s", flux_prompt[:100])
            return flux_prompt
    except Exception as e:
        logger.error("Mistral API error: %s", e)
        return f"A dreamy watercolor illustration about {title}, warm amber and purple tones, cozy nighttime atmosphere, soft focus, bedtime scene, children's book style"


async def _generate_image_fluxapi(prompt: str) -> Optional[bytes]:
    """Generate landscape image via FluxAPI.ai (primary)."""
    api_key = os.getenv("FLUXAPI_KEY", "")
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            # Create task
            resp = await client.post(
                "https://api.fluxapi.ai/api/v1/flux/kontext/generate",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "prompt": prompt[:1500],
                    "aspect_ratio": "16:9",
                    "output_format": "png",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            task_id = data.get("data", {}).get("taskId")

            if not task_id:
                logger.warning("FluxAPI no taskId in response: %s", str(data)[:300])
                return None

            logger.info("FluxAPI task created: %s", task_id)

            # Poll for result via record-info endpoint
            record_url = "https://api.fluxapi.ai/api/v1/flux/kontext/record-info"
            for _ in range(36):  # Up to 3 minutes
                await _async_sleep(5)
                status_resp = await client.get(
                    record_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    params={"taskId": task_id},
                )
                poll_data = status_resp.json().get("data", {})
                flag = poll_data.get("successFlag")

                if flag == 1:  # SUCCESS
                    result_url = poll_data.get("response", {}).get("resultImageUrl")
                    if not result_url:
                        logger.warning("FluxAPI success but no resultImageUrl")
                        return None
                    img_resp = await client.get(result_url, timeout=60.0)
                    if len(img_resp.content) > 1000:
                        logger.info("FluxAPI image generated (%d bytes)", len(img_resp.content))
                        return img_resp.content
                    logger.warning("FluxAPI image too small: %d bytes", len(img_resp.content))
                    return None
                elif flag in (2, 3):  # FAILED
                    logger.warning("FluxAPI task failed: %s", poll_data.get("errorMessage", "unknown"))
                    return None

            logger.warning("FluxAPI task timed out")
            return None
    except Exception as e:
        logger.error("FluxAPI error: %s", e)
        return None


async def _generate_image_pollinations(prompt: str) -> Optional[bytes]:
    """Generate landscape image via Pollinations (fallback 1)."""
    api_key = os.getenv("POLLINATIONS_API_KEY", "")
    try:
        # Truncate prompt for URL safety
        safe_prompt = prompt[:500].replace("\n", " ").strip()
        url = f"https://image.pollinations.ai/prompt/{safe_prompt}"

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(
                url,
                params={"width": 1200, "height": 630, "nologo": "true"},
                headers=headers,
                follow_redirects=True,
            )
            resp.raise_for_status()
            if len(resp.content) > 1000:  # Sanity check
                logger.info("Pollinations image generated (%d bytes)", len(resp.content))
                return resp.content
            return None
    except Exception as e:
        logger.error("Pollinations error: %s", e)
        return None


async def _generate_image_replicate(prompt: str) -> Optional[bytes]:
    """Generate landscape image via Replicate (fallback 2)."""
    api_token = os.getenv("REPLICATE_API_TOKEN", "")
    if not api_token:
        return None

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Create prediction
            resp = await client.post(
                "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions",
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": {
                        "prompt": prompt,
                        "aspect_ratio": "16:9",
                        "output_format": "webp",
                        "output_quality": 90,
                    }
                },
            )
            resp.raise_for_status()
            prediction = resp.json()
            pred_url = prediction.get("urls", {}).get("get")

            if not pred_url:
                return None

            # Poll for result
            for _ in range(30):  # Up to 2.5 minutes
                await _async_sleep(5)
                status_resp = await client.get(
                    pred_url,
                    headers={"Authorization": f"Bearer {api_token}"},
                )
                status_resp.raise_for_status()
                status_data = status_resp.json()

                if status_data.get("status") == "succeeded":
                    output = status_data.get("output")
                    if isinstance(output, list) and output:
                        img_resp = await client.get(output[0])
                        img_resp.raise_for_status()
                        logger.info("Replicate image generated (%d bytes)", len(img_resp.content))
                        return img_resp.content
                    return None
                elif status_data.get("status") == "failed":
                    logger.warning("Replicate prediction failed: %s", status_data.get("error"))
                    return None

            logger.warning("Replicate prediction timed out")
            return None
    except Exception as e:
        logger.error("Replicate error: %s", e)
        return None


async def _async_sleep(seconds: float):
    """Async-compatible sleep."""
    import asyncio
    await asyncio.sleep(seconds)


def _save_cover_webp(image_bytes: bytes, output_path: Path, quality: int = 85) -> bool:
    """Convert image to 1200x630 WebP and save."""
    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGB")

        # Resize to exactly 1200x630 (crop to fit if aspect ratio differs)
        target_w, target_h = 1200, 630
        target_ratio = target_w / target_h
        img_ratio = img.width / img.height

        if img_ratio > target_ratio:
            # Image is wider — crop horizontally
            new_w = int(img.height * target_ratio)
            left = (img.width - new_w) // 2
            img = img.crop((left, 0, left + new_w, img.height))
        elif img_ratio < target_ratio:
            # Image is taller — crop vertically
            new_h = int(img.width / target_ratio)
            top = (img.height - new_h) // 2
            img = img.crop((0, top, img.width, top + new_h))

        img = img.resize((target_w, target_h), Image.LANCZOS)
        img.save(str(output_path), "WebP", quality=quality)
        logger.info("Cover saved: %s (%d bytes)", output_path.name, output_path.stat().st_size)
        return True
    except Exception as e:
        logger.error("Failed to save cover: %s", e)
        return False


@router.post("/posts/{slug}/generate-cover")
async def generate_cover(
    slug: str,
    authorization: Optional[str] = Header(None),
):
    """Generate a FLUX cover image for a blog post. Requires BLOG_SECRET_KEY."""
    verify_blog_key(authorization)

    coll = _get_posts_collection()
    doc = coll.document(slug).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Post not found")

    post = doc.to_dict()

    # Step 1: Generate FLUX prompt from post content
    flux_prompt = await _generate_flux_prompt(post.get("title", ""), post.get("body", ""))

    # Step 2: Generate image (FluxAPI → Pollinations → Replicate)
    image_bytes = None
    source = None

    image_bytes = await _generate_image_fluxapi(flux_prompt)
    if image_bytes:
        source = "FluxAPI"

    if not image_bytes:
        image_bytes = await _generate_image_pollinations(flux_prompt)
        if image_bytes:
            source = "Pollinations"

    if not image_bytes:
        image_bytes = await _generate_image_replicate(flux_prompt)
        if image_bytes:
            source = "Replicate"

    if not image_bytes:
        logger.warning("All image generation providers failed for blog post: %s", slug)
        raise HTTPException(status_code=502, detail="Image generation failed. All providers unavailable.")

    # Step 3: Save as 1200x630 WebP
    covers_dir = _get_covers_dir()
    output_path = covers_dir / f"{slug}.webp"
    if not _save_cover_webp(image_bytes, output_path):
        raise HTTPException(status_code=500, detail="Failed to save cover image")

    # Step 4: Update post with cover info
    cover_url = f"/blog/covers/{slug}.webp"
    cover_data = {
        "url": cover_url,
        "alt": f"Cover image for: {post.get('title', '')}",
        "fluxPrompt": flux_prompt,
    }
    coll.document(slug).update({
        "coverImage": cover_data,
        "seo": {**post.get("seo", {}), "ogImage": cover_url},
    })

    logger.info("Blog cover generated for '%s' via %s", slug, source)

    return {
        "coverUrl": cover_url,
        "fluxPrompt": flux_prompt,
        "source": source,
    }


# ── Admin Helpers ──────────────────────────────────────────────────

@router.get("/admin/posts")
async def admin_list_posts(
    authorization: Optional[str] = Header(None),
):
    """List ALL posts (including drafts) for admin. Requires BLOG_SECRET_KEY."""
    verify_blog_key(authorization)

    coll = _get_posts_collection()
    all_posts = coll.get()
    posts = [doc.to_dict() for doc in all_posts]
    posts.sort(
        key=lambda p: p.get("updatedAt") or p.get("publishedAt") or "1970-01-01T00:00:00Z",
        reverse=True,
    )

    return {"posts": [_post_to_response(p) for p in posts]}


@router.get("/admin/comments")
async def admin_list_comments(
    authorization: Optional[str] = Header(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List recent comments across all posts for moderation. Requires BLOG_SECRET_KEY."""
    verify_blog_key(authorization)

    coll = _get_comments_collection()
    all_comments = [doc.to_dict() for doc in coll.get()]
    all_comments.sort(key=lambda c: c.get("createdAt", ""), reverse=True)

    # Enrich with post title
    posts_coll = _get_posts_collection()
    post_titles = {}
    for doc in posts_coll.get():
        p = doc.to_dict()
        post_titles[p.get("id", "")] = p.get("title", "Unknown")

    for comment in all_comments[:limit]:
        comment["postTitle"] = post_titles.get(comment.get("postId", ""), "Unknown")

    return {"comments": all_comments[:limit]}
