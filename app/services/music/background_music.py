"""Background music management service for DreamWeaver content."""

import logging
from typing import List, Optional, Dict
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class MusicType(str, Enum):
    """Music type categories."""
    AMBIENT = "ambient"
    LULLABY = "lullaby"
    NATURE = "nature"
    INSTRUMENTAL = "instrumental"
    CLASSICAL = "classical"
    RAIN = "rain"


@dataclass
class MusicTrack:
    """Represents a background music track.
    
    Attributes:
        id: Unique track identifier
        name: Track name
        music_type: Type of music (ambient, lullaby, nature, etc.)
        file_path: Path to audio file
        duration_seconds: Track duration in seconds
        artist: Artist name
        license: License type (royalty-free, creative_commons, etc.)
    """
    id: str
    name: str
    music_type: str
    file_path: str
    duration_seconds: int
    artist: str
    license: str


class BackgroundMusicService:
    """Service for managing and selecting background music tracks."""
    
    # Royalty-free music library
    MUSIC_LIBRARY: Dict[str, List[MusicTrack]] = {
        MusicType.AMBIENT: [
            MusicTrack(
                id="ambient_001",
                name="Gentle Pads",
                music_type=MusicType.AMBIENT,
                file_path="assets/music/ambient/gentle_pads.mp3",
                duration_seconds=300,
                artist="DreamWeaver Composer",
                license="royalty-free",
            ),
            MusicTrack(
                id="ambient_002",
                name="Soft Drone",
                music_type=MusicType.AMBIENT,
                file_path="assets/music/ambient/soft_drone.mp3",
                duration_seconds=360,
                artist="DreamWeaver Composer",
                license="royalty-free",
            ),
            MusicTrack(
                id="ambient_003",
                name="Ethereal Atmosphere",
                music_type=MusicType.AMBIENT,
                file_path="assets/music/ambient/ethereal_atmosphere.mp3",
                duration_seconds=480,
                artist="DreamWeaver Composer",
                license="royalty-free",
            ),
            MusicTrack(
                id="ambient_004",
                name="Peaceful Resonance",
                music_type=MusicType.AMBIENT,
                file_path="assets/music/ambient/peaceful_resonance.mp3",
                duration_seconds=420,
                artist="DreamWeaver Composer",
                license="royalty-free",
            ),
        ],
        MusicType.LULLABY: [
            MusicTrack(
                id="lullaby_001",
                name="Music Box",
                music_type=MusicType.LULLABY,
                file_path="assets/music/lullaby/music_box.mp3",
                duration_seconds=180,
                artist="DreamWeaver Composer",
                license="royalty-free",
            ),
            MusicTrack(
                id="lullaby_002",
                name="Gentle Piano",
                music_type=MusicType.LULLABY,
                file_path="assets/music/lullaby/gentle_piano.mp3",
                duration_seconds=240,
                artist="DreamWeaver Composer",
                license="royalty-free",
            ),
            MusicTrack(
                id="lullaby_003",
                name="Soft Bells",
                music_type=MusicType.LULLABY,
                file_path="assets/music/lullaby/soft_bells.mp3",
                duration_seconds=200,
                artist="DreamWeaver Composer",
                license="royalty-free",
            ),
            MusicTrack(
                id="lullaby_004",
                name="Dreamy Melody",
                music_type=MusicType.LULLABY,
                file_path="assets/music/lullaby/dreamy_melody.mp3",
                duration_seconds=220,
                artist="DreamWeaver Composer",
                license="royalty-free",
            ),
        ],
        MusicType.NATURE: [
            MusicTrack(
                id="nature_001",
                name="Rain Sounds",
                music_type=MusicType.NATURE,
                file_path="assets/music/nature/rain_sounds.mp3",
                duration_seconds=600,
                artist="Nature Sounds",
                license="royalty-free",
            ),
            MusicTrack(
                id="nature_002",
                name="Ocean Waves",
                music_type=MusicType.NATURE,
                file_path="assets/music/nature/ocean_waves.mp3",
                duration_seconds=600,
                artist="Nature Sounds",
                license="royalty-free",
            ),
            MusicTrack(
                id="nature_003",
                name="Forest Ambience",
                music_type=MusicType.NATURE,
                file_path="assets/music/nature/forest_ambience.mp3",
                duration_seconds=480,
                artist="Nature Sounds",
                license="royalty-free",
            ),
            MusicTrack(
                id="nature_004",
                name="Chirping Birds",
                music_type=MusicType.NATURE,
                file_path="assets/music/nature/chirping_birds.mp3",
                duration_seconds=300,
                artist="Nature Sounds",
                license="royalty-free",
            ),
        ],
        MusicType.INSTRUMENTAL: [
            MusicTrack(
                id="instrumental_001",
                name="Soft Guitar",
                music_type=MusicType.INSTRUMENTAL,
                file_path="assets/music/instrumental/soft_guitar.mp3",
                duration_seconds=240,
                artist="DreamWeaver Composer",
                license="royalty-free",
            ),
            MusicTrack(
                id="instrumental_002",
                name="Piano Dreams",
                music_type=MusicType.INSTRUMENTAL,
                file_path="assets/music/instrumental/piano_dreams.mp3",
                duration_seconds=300,
                artist="DreamWeaver Composer",
                license="royalty-free",
            ),
            MusicTrack(
                id="instrumental_003",
                name="String Quartet",
                music_type=MusicType.INSTRUMENTAL,
                file_path="assets/music/instrumental/string_quartet.mp3",
                duration_seconds=360,
                artist="DreamWeaver Composer",
                license="royalty-free",
            ),
            MusicTrack(
                id="instrumental_004",
                name="Harp Whispers",
                music_type=MusicType.INSTRUMENTAL,
                file_path="assets/music/instrumental/harp_whispers.mp3",
                duration_seconds=280,
                artist="DreamWeaver Composer",
                license="royalty-free",
            ),
        ],
        MusicType.CLASSICAL: [
            MusicTrack(
                id="classical_001",
                name="Nocturne",
                music_type=MusicType.CLASSICAL,
                file_path="assets/music/classical/nocturne.mp3",
                duration_seconds=360,
                artist="Classical Masters",
                license="public-domain",
            ),
            MusicTrack(
                id="classical_002",
                name="Gentle Sonata",
                music_type=MusicType.CLASSICAL,
                file_path="assets/music/classical/gentle_sonata.mp3",
                duration_seconds=420,
                artist="Classical Masters",
                license="public-domain",
            ),
            MusicTrack(
                id="classical_003",
                name="Lullaby Variation",
                music_type=MusicType.CLASSICAL,
                file_path="assets/music/classical/lullaby_variation.mp3",
                duration_seconds=300,
                artist="Classical Masters",
                license="public-domain",
            ),
        ],
        MusicType.RAIN: [
            MusicTrack(
                id="rain_001",
                name="Light Rain",
                music_type=MusicType.RAIN,
                file_path="assets/music/rain/light_rain.mp3",
                duration_seconds=600,
                artist="Nature Sounds",
                license="royalty-free",
            ),
            MusicTrack(
                id="rain_002",
                name="Thunderstorm",
                music_type=MusicType.RAIN,
                file_path="assets/music/rain/thunderstorm.mp3",
                duration_seconds=600,
                artist="Nature Sounds",
                license="royalty-free",
            ),
            MusicTrack(
                id="rain_003",
                name="Cozy Rain",
                music_type=MusicType.RAIN,
                file_path="assets/music/rain/cozy_rain.mp3",
                duration_seconds=480,
                artist="Nature Sounds",
                license="royalty-free",
            ),
        ],
    }
    
    def __init__(self):
        """Initialize background music service."""
        logger.info("Background music service initialized")
    
    def get_tracks_by_type(self, music_type: str) -> List[MusicTrack]:
        """Get all tracks of a specific type.
        
        Args:
            music_type: Type of music (ambient, lullaby, nature, instrumental, classical, rain)
            
        Returns:
            List of MusicTrack objects of the specified type
            
        Raises:
            ValueError: If music_type is invalid
        """
        try:
            music_type = music_type.lower()
            
            if music_type not in self.MUSIC_LIBRARY:
                raise ValueError(f"Invalid music type: {music_type}")
            
            tracks = self.MUSIC_LIBRARY[music_type]
            logger.debug(f"Retrieved {len(tracks)} tracks of type: {music_type}")
            return tracks
            
        except ValueError as e:
            logger.error(f"Error getting tracks: {e}")
            raise
    
    def select_track(self, music_type: str, target_duration: int) -> Optional[MusicTrack]:
        """Select best matching track for target duration.
        
        Selects a track that is closest in duration to the target, allowing
        for looping of shorter tracks or trimming of longer tracks.
        
        Args:
            music_type: Type of music
            target_duration: Target duration in seconds
            
        Returns:
            Best matching MusicTrack, or None if no tracks available
            
        Raises:
            ValueError: If inputs are invalid
        """
        try:
            if target_duration <= 0:
                raise ValueError("target_duration must be positive")
            
            tracks = self.get_tracks_by_type(music_type)
            
            if not tracks:
                logger.warning(f"No tracks available for type: {music_type}")
                return None
            
            # Find track with closest duration to target
            # Prefer tracks that are shorter (can be looped) over longer (must be trimmed)
            best_track = min(
                tracks,
                key=lambda t: (
                    abs(t.duration_seconds - target_duration),
                    -t.duration_seconds  # Prefer longer if same distance
                )
            )
            
            logger.debug(f"Selected track: {best_track.name} "
                        f"(duration: {best_track.duration_seconds}s for target: {target_duration}s)")
            return best_track
            
        except ValueError as e:
            logger.error(f"Error selecting track: {e}")
            raise
    
    def get_track_url(self, track_id: str) -> Optional[str]:
        """Get URL/path for a specific track.
        
        Args:
            track_id: Track identifier
            
        Returns:
            File path for the track, or None if not found
        """
        try:
            for music_type, tracks in self.MUSIC_LIBRARY.items():
                for track in tracks:
                    if track.id == track_id:
                        logger.debug(f"Found track URL: {track.file_path}")
                        return track.file_path
            
            logger.warning(f"Track not found: {track_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting track URL: {e}")
            return None
    
    def get_all_tracks(self) -> List[MusicTrack]:
        """Get all available tracks.
        
        Returns:
            List of all MusicTrack objects
        """
        all_tracks = []
        for tracks in self.MUSIC_LIBRARY.values():
            all_tracks.extend(tracks)
        return all_tracks
    
    def search_tracks(self, query: str) -> List[MusicTrack]:
        """Search for tracks by name or artist.
        
        Args:
            query: Search query string
            
        Returns:
            List of matching MusicTrack objects
        """
        query_lower = query.lower()
        results = []
        
        for tracks in self.MUSIC_LIBRARY.values():
            for track in tracks:
                if (query_lower in track.name.lower() or
                    query_lower in track.artist.lower()):
                    results.append(track)
        
        logger.debug(f"Found {len(results)} tracks matching: {query}")
        return results
    
    def get_track_info(self, track_id: str) -> Optional[Dict]:
        """Get detailed information about a track.
        
        Args:
            track_id: Track identifier
            
        Returns:
            Dictionary with track information, or None if not found
        """
        try:
            for music_type, tracks in self.MUSIC_LIBRARY.items():
                for track in tracks:
                    if track.id == track_id:
                        return {
                            "id": track.id,
                            "name": track.name,
                            "music_type": track.music_type,
                            "duration_seconds": track.duration_seconds,
                            "artist": track.artist,
                            "license": track.license,
                        }
            
            logger.warning(f"Track info not found: {track_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting track info: {e}")
            return None
