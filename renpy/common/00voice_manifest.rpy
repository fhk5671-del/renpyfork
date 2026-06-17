# Copyright 2004-2026 Tom Rothamel <pytom@bishoujo.us>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

init -1500 python:
    import json
    import re

    _voice_manifest_lookup_cache = None
    _voice_manifest_tag_re_cache = None


    def voice_manifest_normalize_tag_spaces(text):
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        return text.strip()


    def _voice_manifest_tag_re():
        global _voice_manifest_tag_re_cache

        pattern = getattr(config, "voice_manifest_tag_pattern", r"/([A-Za-z][A-Za-z0-9 _'-]{0,60})/")

        if _voice_manifest_tag_re_cache is not None and _voice_manifest_tag_re_cache[0] == pattern:
            return _voice_manifest_tag_re_cache[1]

        if hasattr(pattern, "sub"):
            compiled = pattern
        else:
            compiled = re.compile(str(pattern))

        _voice_manifest_tag_re_cache = (pattern, compiled)
        return compiled


    def _voice_manifest_transform_tag(tag, kind):
        tag = voice_manifest_normalize_tag_spaces(tag)
        callback = getattr(config, "voice_manifest_%s_tag_callback" % kind, None)

        if callable(callback):
            value = callback(tag)
            return "" if value is None else str(value)

        if kind == "tts":
            format_string = getattr(config, "voice_manifest_tts_tag_format", "[{tag}] ")
            return str(format_string).format(tag=tag)

        format_string = getattr(config, "voice_manifest_display_tag_format", "")
        return str(format_string).format(tag=tag)


    def voice_manifest_strip_inline_tags(text):
        if not isinstance(text, str):
            return text

        return voice_manifest_normalize_tag_spaces(
            _voice_manifest_tag_re().sub(lambda m: _voice_manifest_transform_tag(m.group(1), "display"), text)
        )


    def voice_manifest_tts_text(text):
        if not isinstance(text, str):
            return text

        return voice_manifest_normalize_tag_spaces(
            _voice_manifest_tag_re().sub(lambda m: _voice_manifest_transform_tag(m.group(1), "tts"), text)
        )


    def _voice_manifest_say_menu_text_filter(text):
        if not getattr(config, "voice_manifest_enabled", False):
            return text

        if not getattr(config, "voice_manifest_strip_inline_tags", True):
            return text

        return voice_manifest_strip_inline_tags(text)


    if _voice_manifest_say_menu_text_filter not in config.say_menu_text_filters:
        config.say_menu_text_filters.append(_voice_manifest_say_menu_text_filter)


    def voice_manifest_clear_lookup_cache():
        global _voice_manifest_lookup_cache
        _voice_manifest_lookup_cache = None


    def voice_manifest_load_lookup():
        global _voice_manifest_lookup_cache

        if _voice_manifest_lookup_cache is not None:
            return _voice_manifest_lookup_cache

        lookup_path = getattr(config, "voice_manifest_lookup", "audio/voice/manifest/voice_lookup.json")

        try:
            with renpy.file(lookup_path) as handle:
                raw = handle.read()
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                _voice_manifest_lookup_cache = json.loads(raw)
        except Exception:
            _voice_manifest_lookup_cache = {
                "format": 1,
                "audio_pattern": getattr(config, "voice_manifest_audio_pattern", "voice/{voice_id}.ogg"),
                "default_profile": getattr(config, "voice_manifest_default_profile", "default"),
                "by_source_key": {},
                "by_renpy_id": {},
            }

        return _voice_manifest_lookup_cache


    def _voice_manifest_normalize_source_filename(filename):
        filename = str(filename).replace("\\", "/")

        try:
            gamedir = str(config.gamedir).replace("\\", "/")
            basedir = str(config.basedir).replace("\\", "/")

            if filename.startswith(gamedir + "/"):
                filename = filename[len(gamedir) + 1:]
            elif filename.startswith(basedir + "/"):
                filename = filename[len(basedir) + 1:]
        except Exception:
            pass

        if filename.startswith("game/"):
            filename = filename[5:]

        return filename


    def voice_manifest_source_key():
        callback = getattr(config, "voice_manifest_runtime_source_key_callback", None)
        if callable(callback):
            value = callback()
            if value:
                return str(value)

        try:
            filename, line_number = renpy.get_filename_line()
        except Exception:
            return None

        filename = _voice_manifest_normalize_source_filename(filename)
        return filename + ":" + str(line_number)


    def voice_manifest_active_profile(lookup=None):
        if lookup is None:
            lookup = voice_manifest_load_lookup()

        callback = getattr(config, "voice_manifest_profile_callback", None)
        if callable(callback):
            value = callback(lookup)
            if value:
                return str(value)

        return str(lookup.get("default_profile", getattr(config, "voice_manifest_default_profile", "default")))


    def voice_manifest_audio_path(voice_id, lookup=None, profile=None, source_key=None):
        if lookup is None:
            lookup = voice_manifest_load_lookup()

        callback = getattr(config, "voice_manifest_audio_path_callback", None)
        if callable(callback):
            value = callback(voice_id, lookup, profile, source_key)
            if value:
                return str(value)

        pattern = lookup.get("audio_pattern", getattr(config, "voice_manifest_audio_pattern", "voice/{voice_id}.ogg"))
        return str(pattern).format(voice_id=voice_id, profile=profile or "", source_key=source_key or "")


    def voice_manifest_find_voice_id(source_key=None, profile=None, lookup=None):
        if lookup is None:
            lookup = voice_manifest_load_lookup()

        if source_key is None:
            source_key = voice_manifest_source_key()

        if not source_key:
            return None

        if profile is None:
            profile = voice_manifest_active_profile(lookup)

        profile_map = lookup.get("by_source_key", {}).get(source_key)

        if not profile_map and getattr(config, "voice_manifest_renpy_id_fallback", True):
            renpy_id = getattr(renpy.game.context(), "translate_identifier", None)
            if renpy_id:
                profile_map = lookup.get("by_renpy_id", {}).get(renpy_id)

        if not profile_map:
            return None

        default_profile = lookup.get("default_profile", getattr(config, "voice_manifest_default_profile", "default"))
        return profile_map.get(profile) or profile_map.get(default_profile)


    def _voice_manifest_loadable(filename):
        if not getattr(config, "voice_manifest_require_loadable", True):
            return True

        try:
            return renpy.loadable(filename) or renpy.loadable(filename, directory="audio")
        except Exception:
            return False


    def _voice_manifest_play(filename, voice_id, profile, source_key):
        callback = getattr(config, "voice_manifest_play_callback", None)
        if callable(callback):
            return callback(filename, voice_id, profile, source_key)

        tag = None

        try:
            tag = _voice.tag
        except Exception:
            pass

        voice(filename, tag=tag)
        return True


    def _voice_manifest_character_callback(event, interact=True, **kwargs):
        if event != "begin" or not interact:
            return

        if not getattr(config, "voice_manifest_enabled", False):
            return

        if not config.has_voice:
            return

        try:
            if _voice.play and not getattr(config, "voice_manifest_override_voice_statement", False):
                return
        except Exception:
            pass

        lookup = voice_manifest_load_lookup()
        source_key = voice_manifest_source_key()

        if not source_key:
            return

        profile = voice_manifest_active_profile(lookup)
        voice_id = voice_manifest_find_voice_id(source_key, profile, lookup)

        if not voice_id:
            return

        filename = voice_manifest_audio_path(voice_id, lookup, profile, source_key)

        if not filename or not _voice_manifest_loadable(filename):
            return

        _voice_manifest_play(filename, voice_id, profile, source_key)


    if _voice_manifest_character_callback not in config.all_character_callbacks:
        config.all_character_callbacks.append(_voice_manifest_character_callback)
