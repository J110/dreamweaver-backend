def is_complete_silly_song(item: dict) -> bool:
    return bool(item.get("audio_file") and item.get("cover_file"))
