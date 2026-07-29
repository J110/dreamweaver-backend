"""User interaction endpoints for likes, saves, etc."""

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel

from app.dependencies import get_current_user, get_db_client
from app.utils.gating import is_premium, offline_allowed, save_cap
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class _ImmediateTransaction:
    def get(self, target):
        return target.get()

    def set(self, document, data):
        document.set(data)

    def update(self, document, data):
        document.update(data)

    def delete(self, document):
        document.delete()


def _run_transaction(db_client, callback):
    runner = getattr(db_client, "run_transaction", None)
    if callable(runner):
        return runner(callback)
    transaction_factory = getattr(db_client, "transaction", None)
    if callable(transaction_factory):
        from firebase_admin import firestore
        return firestore.transactional(callback)(transaction_factory())
    lock = getattr(db_client, "_lock", None)
    if lock is None:
        return callback(_ImmediateTransaction())
    with lock:
        return callback(_ImmediateTransaction())


def _saved_count_in_transaction(transaction, db_client, user_id):
    query = (
        db_client.collection("interactions")
        .where("user_id", "==", user_id)
        .where("type", "==", "save")
    )
    saves = transaction.get(query)
    return len(saves)


# Response Models
class InteractionResponse(BaseModel):
    """Response model for interactions."""
    success: bool
    data: dict
    message: str


@router.post("/content/{content_id}/like", response_model=InteractionResponse, status_code=status.HTTP_201_CREATED)
async def like_content(
    content_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> InteractionResponse:
    """
    Add a like to content.
    
    Args:
        content_id: ID of content to like
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        InteractionResponse with success status
        
    Raises:
        HTTPException: If content not found
    """
    try:
        user_id = current_user["uid"]
        
        # Get content
        content_doc = db_client.collection("content").document(content_id).get()
        if not content_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Content not found"
            )
        
        content_data = content_doc.to_dict()
        
        # Create interaction record
        interaction_id = f"{user_id}_{content_id}_like"
        interaction_data = {
            "id": interaction_id,
            "user_id": user_id,
            "content_id": content_id,
            "type": "like",
            "created_at": datetime.utcnow(),
        }
        
        db_client.collection("interactions").document(interaction_id).set(interaction_data)
        
        # Increment like count
        current_likes = content_data.get("like_count", 0)
        db_client.collection("content").document(content_id).update({
            "like_count": current_likes + 1,
            "updated_at": datetime.utcnow(),
        })
        
        logger.info(f"User {user_id} liked content {content_id}")
        
        return InteractionResponse(
            success=True,
            data={"content_id": content_id, "like_count": current_likes + 1},
            message="Content liked successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error liking content: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to like content: {str(e)}"
        )


@router.delete("/content/{content_id}/like", response_model=InteractionResponse)
async def unlike_content(
    content_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> InteractionResponse:
    """
    Remove a like from content.
    
    Args:
        content_id: ID of content to unlike
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        InteractionResponse with success status
        
    Raises:
        HTTPException: If content not found
    """
    try:
        user_id = current_user["uid"]
        
        # Get content
        content_doc = db_client.collection("content").document(content_id).get()
        if not content_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Content not found"
            )
        
        content_data = content_doc.to_dict()
        
        # Delete interaction record
        interaction_id = f"{user_id}_{content_id}_like"
        db_client.collection("interactions").document(interaction_id).delete()
        
        # Decrement like count
        current_likes = max(0, content_data.get("like_count", 1) - 1)
        db_client.collection("content").document(content_id).update({
            "like_count": current_likes,
            "updated_at": datetime.utcnow(),
        })
        
        logger.info(f"User {user_id} unliked content {content_id}")
        
        return InteractionResponse(
            success=True,
            data={"content_id": content_id, "like_count": current_likes},
            message="Content unliked successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unliking content: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to unlike content: {str(e)}"
        )


@router.post("/content/{content_id}/save", response_model=InteractionResponse, status_code=status.HTTP_201_CREATED)
async def save_content(
    content_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> InteractionResponse:
    """
    Save content to user's library.
    
    Args:
        content_id: ID of content to save
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        InteractionResponse with success status
        
    Raises:
        HTTPException: If content not found
    """
    try:
        user_id = current_user["uid"]

        save_id = f"{user_id}_{content_id}_save"
        save_ref = db_client.collection("interactions").document(save_id)
        content_ref = db_client.collection("content").document(content_id)
        counter_ref = db_client.collection("user_save_counters").document(user_id)
        cap = save_cap(current_user)
        def save_in_transaction(transaction):
            content_doc = transaction.get(content_ref)
            if not content_doc.exists:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Content not found",
                )
            save_doc = transaction.get(save_ref)
            counter_doc = transaction.get(counter_ref)
            current_count = (
                max(0, int((counter_doc.to_dict() or {}).get("saved_count", 0)))
                if counter_doc.exists
                else _saved_count_in_transaction(transaction, db_client, user_id)
            )
            already_saved = save_doc.exists
            now = datetime.now(timezone.utc)
            if not already_saved and cap is not None and current_count >= cap:
                if not counter_doc.exists:
                    transaction.set(counter_ref, {
                        "user_id": user_id,
                        "saved_count": current_count,
                        "updated_at": now,
                    })
                return {
                    "saved": False,
                    "saved_count": current_count,
                    "content_save_count": (content_doc.to_dict() or {}).get("save_count", 0),
                }
            content_save_count = max(0, int((content_doc.to_dict() or {}).get("save_count", 0)))
            if not already_saved:
                transaction.set(save_ref, {
                    "id": save_id,
                    "user_id": user_id,
                    "content_id": content_id,
                    "type": "save",
                    "created_at": now,
                })
                current_count += 1
                content_save_count += 1
                transaction.update(content_ref, {
                    "save_count": content_save_count,
                    "updated_at": now,
                })
            if not counter_doc.exists or not already_saved:
                transaction.set(counter_ref, {
                    "user_id": user_id,
                    "saved_count": current_count,
                    "updated_at": now,
                })
            return {
                "saved": True,
                "saved_count": current_count,
                "content_save_count": content_save_count,
            }

        result = _run_transaction(db_client, save_in_transaction)
        if not result["saved"]:
            logger.info(f"User {user_id} hit save cap ({cap}) for {content_id}")
            return InteractionResponse(
                success=True,
                data={
                    "content_id": content_id,
                    "saved": False,
                    "liked": False,
                    "cap_reached": True,
                    "saved_count": result["saved_count"],
                    "save_cap": cap,
                    "offline_allowed": offline_allowed(current_user),
                },
                message="Save cap reached",
            )

        logger.info(f"User {user_id} saved content {content_id}")
        return InteractionResponse(
            success=True,
            data={
                "content_id": content_id,
                "save_count": result["content_save_count"],
                "saved": True,
                "liked": False,
                "cap_reached": False,
                "saved_count": result["saved_count"] if cap is not None else None,
                "save_cap": cap,
                "offline_allowed": offline_allowed(current_user),
            },
            message="Content saved successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving content: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to save content: {str(e)}"
        )


@router.delete("/content/{content_id}/save", response_model=InteractionResponse)
async def unsave_content(
    content_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> InteractionResponse:
    """
    Remove content from user's saved library.
    
    Args:
        content_id: ID of content to unsave
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        InteractionResponse with success status
        
    Raises:
        HTTPException: If content not found
    """
    try:
        user_id = current_user["uid"]
        
        interaction_id = f"{user_id}_{content_id}_save"
        save_ref = db_client.collection("interactions").document(interaction_id)
        content_ref = db_client.collection("content").document(content_id)
        counter_ref = db_client.collection("user_save_counters").document(user_id)

        def unsave_in_transaction(transaction):
            content_doc = transaction.get(content_ref)
            if not content_doc.exists:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Content not found",
                )
            save_doc = transaction.get(save_ref)
            counter_doc = transaction.get(counter_ref)
            current_count = (
                max(0, int((counter_doc.to_dict() or {}).get("saved_count", 0)))
                if counter_doc.exists
                else _saved_count_in_transaction(transaction, db_client, user_id)
            )
            content_save_count = max(0, int((content_doc.to_dict() or {}).get("save_count", 0)))
            now = datetime.now(timezone.utc)
            if save_doc.exists:
                current_count = max(0, current_count - 1)
                content_save_count = max(0, content_save_count - 1)
                transaction.delete(save_ref)
                transaction.update(content_ref, {
                    "save_count": content_save_count,
                    "updated_at": now,
                })
            transaction.set(counter_ref, {
                "user_id": user_id,
                "saved_count": current_count,
                "updated_at": now,
            })
            return content_save_count

        current_saves = _run_transaction(db_client, unsave_in_transaction)
        
        logger.info(f"User {user_id} unsaved content {content_id}")
        
        return InteractionResponse(
            success=True,
            data={"content_id": content_id, "save_count": current_saves},
            message="Content unsaved successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unsaving content: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to unsave content: {str(e)}"
        )


@router.get("/me/likes", response_model=InteractionResponse)
async def get_user_likes(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> InteractionResponse:
    """
    Get list of content IDs the user has liked.
    
    Args:
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        InteractionResponse with list of liked content IDs
    """
    try:
        user_id = current_user["uid"]

        # Get all like interactions for user
        interactions = db_client.collection("interactions").where("user_id", "==", user_id).where("type", "==", "like").get()

        liked_ids = [interaction.to_dict().get("content_id") for interaction in interactions]

        # Fetch full content objects for each liked ID
        items = []
        for cid in liked_ids:
            content_doc = db_client.collection("content").document(cid).get()
            if content_doc.exists:
                content_data = content_doc.to_dict()
                content_data["is_liked"] = True
                items.append(content_data)

        return InteractionResponse(
            success=True,
            data={"items": items, "liked_content_ids": liked_ids, "total": len(items)},
            message="User likes retrieved successfully"
        )

    except Exception as e:
        logger.error(f"Error getting user likes: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get likes: {str(e)}"
        )


@router.get("/me/saves", response_model=InteractionResponse)
async def get_user_saves(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> InteractionResponse:
    """
    Get list of content IDs the user has saved.
    
    Args:
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        InteractionResponse with list of saved content IDs
    """
    try:
        user_id = current_user["uid"]

        # Get all save interactions for user
        interactions = db_client.collection("interactions").where("user_id", "==", user_id).where("type", "==", "save").get()

        saved_ids = [interaction.to_dict().get("content_id") for interaction in interactions]

        # Fetch full content objects for each saved ID
        items = []
        for cid in saved_ids:
            content_doc = db_client.collection("content").document(cid).get()
            if content_doc.exists:
                content_data = content_doc.to_dict()
                content_data["is_saved"] = True
                items.append(content_data)

        return InteractionResponse(
            success=True,
            data={
                "items": items,
                "saved_content_ids": saved_ids,
                "total": len(items),
                # None when paywall off (unlimited). Favorites page shows the
                # "n of cap saved — Premium unlocks 30" invitation off these.
                "save_cap": save_cap(current_user),
                "effective_premium": is_premium(current_user),
                "offline_allowed": offline_allowed(current_user),
            },
            message="User saves retrieved successfully"
        )

    except Exception as e:
        logger.error(f"Error getting user saves: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get saves: {str(e)}"
        )
