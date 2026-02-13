"""Groq API integration for text generation."""

import logging
import time
from typing import Optional
from datetime import datetime, timedelta

try:
    from groq import Groq
except ImportError:
    raise ImportError("groq package not installed. Install with: pip install groq")

logger = logging.getLogger(__name__)


class RateLimitTracker:
    """Track rate limit usage for Groq API."""
    
    def __init__(self, requests_per_minute: int = 30):
        """
        Initialize rate limit tracker.
        
        Args:
            requests_per_minute: Maximum requests allowed per minute
        """
        self.requests_per_minute = requests_per_minute
        self.request_times: list[datetime] = []
    
    def check_rate_limit(self) -> bool:
        """
        Check if request can be made without exceeding rate limit.
        
        Returns:
            True if within rate limit, False otherwise
        """
        now = datetime.now()
        # Remove timestamps older than 1 minute
        self.request_times = [
            t for t in self.request_times
            if now - t < timedelta(minutes=1)
        ]
        
        return len(self.request_times) < self.requests_per_minute
    
    def record_request(self) -> None:
        """Record a request timestamp."""
        self.request_times.append(datetime.now())
    
    def get_wait_time(self) -> float:
        """
        Get seconds to wait before next request.
        
        Returns:
            Seconds to wait, or 0 if no wait needed
        """
        now = datetime.now()
        self.request_times = [
            t for t in self.request_times
            if now - t < timedelta(minutes=1)
        ]
        
        if len(self.request_times) < self.requests_per_minute:
            return 0.0
        
        oldest_request = self.request_times[0]
        wait_time = (oldest_request + timedelta(minutes=1) - now).total_seconds()
        return max(0.0, wait_time)


class GroqService:
    """Service for text generation using Groq API."""
    
    # Available models
    FAST_MODEL = "llama-3.1-8b-instant"
    QUALITY_MODEL = "llama-3.1-70b-versatile"
    AVAILABLE_MODELS = [FAST_MODEL, QUALITY_MODEL]
    
    # Default parameters
    DEFAULT_MAX_TOKENS = 1024
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_TIMEOUT = 30  # seconds
    DEFAULT_RETRIES = 3
    
    def __init__(
        self,
        api_key: str,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES
    ):
        """
        Initialize Groq service.
        
        Args:
            api_key: Groq API key
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            
        Raises:
            ValueError: If api_key is empty
        """
        if not api_key:
            raise ValueError("API key cannot be empty")
        
        self.client = Groq(api_key=api_key)
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limiter = RateLimitTracker()
        
        logger.info("GroqService initialized with timeout=%s, max_retries=%s",
                   timeout, max_retries)
    
    def generate_text(
        self,
        prompt: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        model: str = FAST_MODEL,
    ) -> str:
        """
        Generate text using Groq API with retry logic and rate limiting.
        
        Args:
            prompt: The prompt to generate text from
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (0.0-2.0)
            model: Model to use (fast or quality)
            
        Returns:
            Generated text
            
        Raises:
            ValueError: If prompt is empty or model is invalid
            RuntimeError: If generation fails after retries
        """
        if not prompt:
            raise ValueError("Prompt cannot be empty")
        
        if model not in self.AVAILABLE_MODELS:
            raise ValueError(f"Invalid model. Must be one of {self.AVAILABLE_MODELS}")
        
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("Temperature must be between 0.0 and 2.0")
        
        if max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")
        
        # Check rate limit
        wait_time = self.rate_limiter.get_wait_time()
        if wait_time > 0:
            logger.warning("Rate limit reached, waiting %.2f seconds", wait_time)
            time.sleep(wait_time)
        
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    "Generating text (attempt %d/%d) with model=%s, "
                    "max_tokens=%d, temperature=%.2f",
                    attempt + 1, self.max_retries, model, max_tokens, temperature
                )
                
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=self.timeout,
                )
                
                # Record successful request for rate limiting
                self.rate_limiter.record_request()
                
                generated_text = response.choices[0].message.content.strip()
                
                logger.info(
                    "Text generated successfully with model=%s, "
                    "tokens_used=%s",
                    model, response.usage.total_tokens
                )
                
                return generated_text
            
            except Exception as e:
                last_error = e
                logger.warning(
                    "Generation attempt %d/%d failed: %s",
                    attempt + 1, self.max_retries, str(e)
                )
                
                # Exponential backoff: wait 1s, 2s, 4s between retries
                if attempt < self.max_retries - 1:
                    wait_seconds = 2 ** attempt
                    logger.debug("Retrying after %d seconds", wait_seconds)
                    time.sleep(wait_seconds)
        
        # All retries failed
        error_message = (
            f"Text generation failed after {self.max_retries} attempts. "
            f"Last error: {str(last_error)}"
        )
        logger.error(error_message)
        raise RuntimeError(error_message) from last_error
    
    def get_rate_limit_status(self) -> dict:
        """
        Get current rate limit status.
        
        Returns:
            Dictionary with rate limit information
        """
        now = datetime.now()
        recent_requests = [
            t for t in self.rate_limiter.request_times
            if now - t < timedelta(minutes=1)
        ]
        
        return {
            "requests_in_last_minute": len(recent_requests),
            "limit_per_minute": self.rate_limiter.requests_per_minute,
            "remaining_requests": max(
                0,
                self.rate_limiter.requests_per_minute - len(recent_requests)
            ),
            "seconds_until_reset": self.rate_limiter.get_wait_time(),
        }
