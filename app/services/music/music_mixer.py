"""Audio mixing service for speech and background music."""

import logging
from typing import Optional, Tuple
from io import BytesIO
import numpy as np

logger = logging.getLogger(__name__)


class MusicMixer:
    """Service for mixing speech audio with background music."""
    
    # Default mix parameters
    DEFAULT_MUSIC_VOLUME = 0.2  # 20% of speech volume
    DEFAULT_FADE_IN_DURATION = 3.0  # 3 seconds
    DEFAULT_FADE_OUT_DURATION = 5.0  # 5 seconds
    
    # Audio ducking parameters
    DEFAULT_DUCKING_THRESHOLD = 0.1  # Speech detection threshold
    DEFAULT_DUCKING_REDUCTION = -6  # dB reduction when speech detected
    
    def __init__(self):
        """Initialize music mixer."""
        logger.info("Music mixer service initialized")
    
    def mix_speech_with_music(self, speech_audio: bytes, music_track_path: str,
                             music_volume: float = DEFAULT_MUSIC_VOLUME) -> Optional[bytes]:
        """Mix speech audio with background music.
        
        Pipeline:
        1. Load speech audio
        2. Load background music
        3. Loop music to match speech duration
        4. Apply ducking (reduce music when speech detected)
        5. Add fade-in (first 3s) and fade-out (last 5s) on music
        6. Mix together
        7. Return combined audio bytes
        
        Args:
            speech_audio: Speech audio as bytes (MP3 or WAV)
            music_track_path: Path to background music file
            music_volume: Volume multiplier for music (0.0-1.0, default 0.2)
            
        Returns:
            Mixed audio as bytes (MP3), or None if error occurred
            
        Raises:
            ValueError: If inputs are invalid
        """
        try:
            if not speech_audio:
                raise ValueError("speech_audio cannot be empty")
            if not music_track_path:
                raise ValueError("music_track_path cannot be empty")
            if not 0.0 <= music_volume <= 1.0:
                raise ValueError("music_volume must be between 0.0 and 1.0")
            
            logger.info(f"Mixing speech with music from: {music_track_path}")
            
            # Step 1: Load speech audio
            speech_data = self._load_audio(speech_audio)
            if speech_data is None:
                raise ValueError("Failed to load speech audio")
            
            speech_samples, speech_sr = speech_data
            speech_duration = len(speech_samples) / speech_sr
            logger.debug(f"Speech duration: {speech_duration:.2f}s at {speech_sr}Hz")
            
            # Step 2: Load background music
            music_data = self._load_audio_from_file(music_track_path)
            if music_data is None:
                raise ValueError(f"Failed to load music: {music_track_path}")
            
            music_samples, music_sr = music_data
            
            # Step 3: Loop music to match speech duration
            looped_music = self._loop_to_duration(music_samples, music_sr,
                                                 speech_duration)
            logger.debug(f"Looped music to {len(looped_music) / music_sr:.2f}s")
            
            # Resample music to match speech sample rate
            if music_sr != speech_sr:
                looped_music = self._resample_audio(looped_music, music_sr, speech_sr)
            
            # Step 4: Apply audio ducking
            ducked_music = self._apply_ducking(speech_samples, looped_music)
            logger.debug("Applied audio ducking")
            
            # Step 5: Apply fade-in and fade-out
            faded_music = self._apply_fades(ducked_music, speech_sr,
                                           self.DEFAULT_FADE_IN_DURATION,
                                           self.DEFAULT_FADE_OUT_DURATION)
            logger.debug("Applied fade-in and fade-out")
            
            # Step 6: Mix speech and music
            # Speech at normal level, music at specified volume
            mixed_samples = (speech_samples +
                           faded_music * music_volume)
            
            # Normalize to prevent clipping
            max_amplitude = np.max(np.abs(mixed_samples))
            if max_amplitude > 1.0:
                mixed_samples = mixed_samples / max_amplitude * 0.95
            
            logger.debug("Audio mixed and normalized")
            
            # Step 7: Convert back to bytes
            mixed_audio = self._samples_to_bytes(mixed_samples, speech_sr)
            logger.info("Speech and music mixed successfully")
            
            return mixed_audio
            
        except Exception as e:
            logger.error(f"Error mixing speech with music: {e}")
            return None
    
    def _load_audio(self, audio_bytes: bytes) -> Optional[Tuple[np.ndarray, int]]:
        """Load audio from bytes.
        
        Args:
            audio_bytes: Audio data as bytes
            
        Returns:
            Tuple of (audio_samples, sample_rate), or None if error
        """
        try:
            # Try using librosa if available
            try:
                import librosa
                audio_io = BytesIO(audio_bytes)
                samples, sr = librosa.load(audio_io, sr=None)
                return samples, sr
            except ImportError:
                logger.warning("librosa not available, using fallback")
                # Fallback: try scipy/soundfile
                try:
                    import soundfile as sf
                    audio_io = BytesIO(audio_bytes)
                    samples, sr = sf.read(audio_io)
                    return samples.astype(np.float32), sr
                except ImportError:
                    logger.error("No audio loading library available")
                    return None
        except Exception as e:
            logger.error(f"Error loading audio bytes: {e}")
            return None
    
    def _load_audio_from_file(self, file_path: str) -> Optional[Tuple[np.ndarray, int]]:
        """Load audio from file path.
        
        Args:
            file_path: Path to audio file
            
        Returns:
            Tuple of (audio_samples, sample_rate), or None if error
        """
        try:
            try:
                import librosa
                samples, sr = librosa.load(file_path, sr=None)
                return samples, sr
            except ImportError:
                try:
                    import soundfile as sf
                    samples, sr = sf.read(file_path)
                    return samples.astype(np.float32), sr
                except ImportError:
                    logger.error("No audio loading library available")
                    return None
        except Exception as e:
            logger.error(f"Error loading audio file: {e}")
            return None
    
    def _loop_to_duration(self, audio_samples: np.ndarray, sample_rate: int,
                         target_duration: float) -> np.ndarray:
        """Loop audio to match target duration.
        
        Args:
            audio_samples: Audio samples array
            sample_rate: Sample rate in Hz
            target_duration: Target duration in seconds
            
        Returns:
            Extended audio samples
        """
        try:
            target_samples = int(target_duration * sample_rate)
            current_length = len(audio_samples)
            
            if current_length >= target_samples:
                return audio_samples[:target_samples]
            
            # Calculate how many times to loop
            num_loops = (target_samples // current_length) + 1
            looped = np.tile(audio_samples, num_loops)
            
            # Trim to exact target length
            looped = looped[:target_samples]
            
            return looped
            
        except Exception as e:
            logger.error(f"Error looping audio: {e}")
            return audio_samples
    
    def _resample_audio(self, samples: np.ndarray, orig_sr: int,
                       target_sr: int) -> np.ndarray:
        """Resample audio to different sample rate.
        
        Args:
            samples: Audio samples
            orig_sr: Original sample rate
            target_sr: Target sample rate
            
        Returns:
            Resampled audio
        """
        try:
            if orig_sr == target_sr:
                return samples
            
            try:
                import librosa
                return librosa.resample(samples, orig_sr=orig_sr, target_sr=target_sr)
            except ImportError:
                logger.warning("librosa not available, simple resampling")
                ratio = target_sr / orig_sr
                new_length = int(len(samples) * ratio)
                return np.interp(np.linspace(0, len(samples)-1, new_length),
                               np.arange(len(samples)), samples)
        except Exception as e:
            logger.error(f"Error resampling audio: {e}")
            return samples
    
    def _apply_ducking(self, speech_samples: np.ndarray,
                      music_samples: np.ndarray,
                      threshold: float = DEFAULT_DUCKING_THRESHOLD,
                      reduction_db: float = DEFAULT_DUCKING_REDUCTION) -> np.ndarray:
        """Apply audio ducking (reduce music when speech detected).
        
        Args:
            speech_samples: Speech audio samples
            music_samples: Music audio samples
            threshold: Voice activity detection threshold (0.0-1.0)
            reduction_db: Reduction in dB when speech detected
            
        Returns:
            Ducked music samples
        """
        try:
            # Normalize speech for voice detection
            speech_norm = np.abs(speech_samples)
            
            # Simple voice activity detection: RMS energy per frame
            frame_size = len(speech_samples) // len(music_samples)
            if frame_size < 1:
                frame_size = 1
            
            # Detect speech activity
            speech_active = np.zeros(len(music_samples))
            for i in range(len(music_samples)):
                start_idx = min(i * frame_size, len(speech_norm) - 1)
                end_idx = min((i + 1) * frame_size, len(speech_norm))
                
                if end_idx > start_idx:
                    frame_energy = np.sqrt(np.mean(
                        speech_norm[start_idx:end_idx] ** 2
                    ))
                    if frame_energy > threshold:
                        speech_active[i] = 1
            
            # Apply smooth ducking
            ducking_factor = np.ones(len(music_samples))
            reduction_factor = 10 ** (reduction_db / 20)  # Convert dB to linear
            
            # Smooth the ducking factor
            for i in range(len(ducking_factor)):
                if speech_active[i]:
                    ducking_factor[i] = reduction_factor
            
            # Apply smoothing for gradual transitions
            smoothed_factor = np.ones(len(ducking_factor))
            alpha = 0.1  # Smoothing factor
            for i in range(1, len(smoothed_factor)):
                smoothed_factor[i] = (alpha * ducking_factor[i] +
                                    (1 - alpha) * smoothed_factor[i - 1])
            
            # Apply ducking
            ducked_music = music_samples * smoothed_factor
            
            return ducked_music
            
        except Exception as e:
            logger.error(f"Error applying ducking: {e}")
            return music_samples
    
    def _apply_fades(self, samples: np.ndarray, sample_rate: int,
                    fade_in_duration: float, fade_out_duration: float) -> np.ndarray:
        """Apply fade-in and fade-out effects.
        
        Args:
            samples: Audio samples
            sample_rate: Sample rate
            fade_in_duration: Fade-in duration in seconds
            fade_out_duration: Fade-out duration in seconds
            
        Returns:
            Audio with fades applied
        """
        try:
            fade_in_samples = int(fade_in_duration * sample_rate)
            fade_out_samples = int(fade_out_duration * sample_rate)
            
            result = samples.copy()
            
            # Fade in
            if fade_in_samples > 0 and fade_in_samples < len(result):
                fade_in_envelope = np.linspace(0, 1, fade_in_samples)
                result[:fade_in_samples] *= fade_in_envelope
            
            # Fade out
            if fade_out_samples > 0 and fade_out_samples < len(result):
                fade_out_envelope = np.linspace(1, 0, fade_out_samples)
                result[-fade_out_samples:] *= fade_out_envelope
            
            return result
            
        except Exception as e:
            logger.error(f"Error applying fades: {e}")
            return samples
    
    def _samples_to_bytes(self, samples: np.ndarray, sample_rate: int) -> Optional[bytes]:
        """Convert audio samples to MP3 bytes.
        
        Args:
            samples: Audio samples
            sample_rate: Sample rate
            
        Returns:
            MP3 audio as bytes, or None if error
        """
        try:
            try:
                import pydub
                from pydub.utils import mediainfo
                
                # Convert numpy array to audio segment
                # Ensure samples are in correct range
                samples_int16 = np.int16(samples * 32767)
                audio_segment = pydub.AudioSegment(
                    samples_int16.tobytes(),
                    frame_rate=sample_rate,
                    sample_width=2,
                    channels=1
                )
                
                # Export to MP3
                output = BytesIO()
                audio_segment.export(output, format="mp3", bitrate="128k")
                output.seek(0)
                return output.read()
                
            except ImportError:
                logger.warning("pydub not available, returning WAV")
                # Fallback to WAV
                import wave
                output = BytesIO()
                samples_int16 = np.int16(samples * 32767)
                
                with wave.open(output, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(samples_int16.tobytes())
                
                output.seek(0)
                return output.read()
                
        except Exception as e:
            logger.error(f"Error converting samples to bytes: {e}")
            return None
