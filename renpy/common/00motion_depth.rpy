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
    import math


    def _sprite_motion_jump_settings():
        return getattr(config, "sprite_motion_jump_settings", {}) or {}


    def _sprite_motion_nudge_settings():
        return getattr(config, "sprite_motion_nudge_settings", {}) or {}


    def _sprite_motion_deform_settings():
        return getattr(config, "sprite_motion_deform_settings", {}) or {}


    def _sprite_motion_state():
        state = getattr(renpy.store, "_sprite_motion_current_state", None)

        if state is None:
            state = {
                "offsets": {},
                "counts": {},
                "pending_direction_signs": {},
                "sprites": {},
                "suppress_tags": {},
                "suppress_next": False,
            }
            renpy.store._sprite_motion_current_state = state

        return state


    def _sprite_motion_layer(tag=None):
        callback = getattr(config, "sprite_motion_layer_callback", None)

        if callable(callback):
            layer = callback(tag)
            if layer:
                return str(layer)

        return getattr(config, "sprite_motion_layer", "master")


    def _sprite_motion_showing(tag, layer=None):
        try:
            return renpy.showing(tag, layer=layer or _sprite_motion_layer(tag))
        except Exception:
            return False


    def _sprite_motion_offset(tag):
        state = _sprite_motion_state()
        return float(state.get("offsets", {}).get(tag, 0.0))


    def _sprite_motion_set_offset(tag, offset):
        state = _sprite_motion_state()
        offsets = state.setdefault("offsets", {})
        offsets[tag] = float(offset)


    def _sprite_motion_clear_offset(tag):
        _sprite_motion_set_offset(tag, 0.0)


    def _sprite_motion_direction_sign(direction):
        if direction is None:
            return None

        if isinstance(direction, (int, float)):
            if direction < 0:
                return -1
            if direction > 0:
                return 1
            return None

        direction = str(direction).lower()

        if direction in ("left", "-1"):
            return -1

        if direction in ("right", "1"):
            return 1

        return None


    def _sprite_motion_mirrored_facing(facing, mirror=False):
        if facing == "left" and mirror:
            return "right"

        if facing == "right" and mirror:
            return "left"

        return facing


    def _sprite_motion_facing_group(facing):
        if facing == "left":
            return "left"

        if facing in ("right", "front"):
            return "right_front"

        return None


    def _sprite_motion_facing_transition_sign(previous_facing, current_facing):
        previous_group = _sprite_motion_facing_group(previous_facing)
        current_group = _sprite_motion_facing_group(current_facing)

        if previous_group == "left" and current_group == "right_front":
            return 1

        if previous_group == "right_front" and current_group == "left":
            return -1

        return None


    def _sprite_motion_lookup_facing(tag, attrs=(), mirror=False):
        attrs = tuple(str(i) for i in (attrs or ()))
        callback = getattr(config, "sprite_motion_facing_callback", None)

        if callable(callback):
            facing = callback(tag, attrs, mirror)
            if facing is not None:
                facing = str(facing).lower()
                if facing in ("left", "right", "front"):
                    return _sprite_motion_mirrored_facing(facing, mirror)

        data = getattr(config, "sprite_motion_facing_map", {}) or {}
        candidates = []

        if attrs:
            candidates.append(" ".join(attrs))
            candidates.extend(attrs)

        candidates.append("*")

        for key in (str(tag), "default", "*"):
            tag_facings = data.get(key, None)

            if isinstance(tag_facings, str):
                facing = tag_facings.lower()
                if facing in ("left", "right", "front"):
                    return _sprite_motion_mirrored_facing(facing, mirror)

            if not isinstance(tag_facings, dict):
                continue

            for attr in candidates:
                facing = tag_facings.get(attr, None)

                if facing is None:
                    continue

                facing = str(facing).lower()

                if facing in ("left", "right", "front"):
                    return _sprite_motion_mirrored_facing(facing, mirror)

        return None


    def _sprite_motion_set_pending_nudge_sign(tag, sign):
        state = _sprite_motion_state()
        pending = state.setdefault("pending_direction_signs", {})

        sign = _sprite_motion_direction_sign(sign)

        if sign is None:
            pending.pop(tag, None)
        else:
            pending[tag] = sign


    def _sprite_motion_consume_pending_nudge_sign(tag):
        state = _sprite_motion_state()
        pending = state.setdefault("pending_direction_signs", {})
        return _sprite_motion_direction_sign(pending.pop(tag, None))


    def sprite_motion_queue_nudge_direction(tag, direction):
        _sprite_motion_set_pending_nudge_sign(tag, direction)


    def sprite_motion_note_facing(tag, attrs=None, mirror=False, facing=None):
        state = _sprite_motion_state()
        sprites = state.setdefault("sprites", {})

        if attrs is None:
            try:
                attrs = renpy.get_attributes(tag, layer=_sprite_motion_layer(tag)) or ()
            except Exception:
                attrs = ()

        attrs = tuple(str(i) for i in (attrs or ()))

        if facing is None:
            facing = _sprite_motion_lookup_facing(tag, attrs, mirror)
        elif facing is not None:
            facing = str(facing).lower()
            if facing not in ("left", "right", "front"):
                facing = None
            else:
                facing = _sprite_motion_mirrored_facing(facing, mirror)

        previous = sprites.get(tag, {}) or {}
        previous_attrs = tuple(previous.get("attrs", ()))
        previous_mirror = bool(previous.get("mirror", False))
        previous_facing = previous.get("facing", None)

        changed = bool(previous) and (attrs != previous_attrs or bool(mirror) != previous_mirror or facing != previous_facing)

        if changed:
            _sprite_motion_set_pending_nudge_sign(tag, _sprite_motion_facing_transition_sign(previous_facing, facing))
        else:
            _sprite_motion_set_pending_nudge_sign(tag, None)

        sprites[tag] = dict(attrs=attrs, mirror=bool(mirror), facing=facing)
        return facing


    def _sprite_motion_store_facing(tag, attrs=(), mirror=False, facing=None):
        state = _sprite_motion_state()
        sprites = state.setdefault("sprites", {})

        attrs = tuple(str(i) for i in (attrs or ()))

        if facing is None:
            facing = _sprite_motion_lookup_facing(tag, attrs, mirror)

        sprites[tag] = dict(attrs=attrs, mirror=bool(mirror), facing=facing)
        return facing


    def sprite_motion_suppress_next_auto_nudge(tag=None):
        state = _sprite_motion_state()

        if tag:
            state.setdefault("suppress_tags", {})[tag] = True
        else:
            state["suppress_next"] = True


    def _sprite_motion_consume_auto_nudge_suppression(tag):
        state = _sprite_motion_state()

        if state.get("suppress_next", False):
            state["suppress_next"] = False
            _sprite_motion_set_pending_nudge_sign(tag, None)
            return True

        suppress_tags = state.setdefault("suppress_tags", {})

        if tag and suppress_tags.get(tag, False):
            suppress_tags[tag] = False
            _sprite_motion_set_pending_nudge_sign(tag, None)
            return True

        return False


    def _sprite_motion_nudge_direction(tag, direction, automatic):
        explicit_sign = _sprite_motion_direction_sign(direction)

        if explicit_sign is not None:
            _sprite_motion_set_pending_nudge_sign(tag, None)
            return explicit_sign

        pending_sign = _sprite_motion_consume_pending_nudge_sign(tag)

        if pending_sign is not None:
            return pending_sign

        state = _sprite_motion_state()
        offsets = state.setdefault("offsets", {})
        counts = state.setdefault("counts", {})

        count = int(counts.get(tag, 0)) + 1
        counts[tag] = count

        if count % 3 == 0:
            current = float(offsets.get(tag, 0.0))

            if current > 0.0:
                return -1

            if current < 0.0:
                return 1

        try:
            return renpy.random.choice((-1, 1))
        except Exception:
            return 1


    def _sprite_motion_nudge_targets(tag, direction=None, amount=1.0, automatic=False):
        settings = _sprite_motion_nudge_settings()
        distance = float(settings.get("distance", 10.0)) * float(amount)
        max_offset = float(settings.get("maxOffset", settings.get("max_offset", 24.0)))
        current = _sprite_motion_offset(tag)
        sign = _sprite_motion_nudge_direction(tag, direction, automatic)

        target = current + sign * distance

        if max_offset > 0.0:
            if target > max_offset:
                target = max(current - distance, -max_offset)
            elif target < -max_offset:
                target = min(current + distance, max_offset)

            target = min(max(target, -max_offset), max_offset)

        _sprite_motion_set_offset(tag, target)
        return current, target


    def _sprite_motion_optional_image_exists(name):
        name = str(name)

        try:
            if renpy.has_image(tuple(name.split()), exact=True):
                return True
        except Exception:
            pass

        if "." in name:
            try:
                if renpy.loadable(name):
                    return True
            except Exception:
                pass

        for extension in (".png", ".webp", ".jpg", ".jpeg"):
            for prefix in ("", "images/"):
                try:
                    if renpy.loadable("%s%s%s" % (prefix, name, extension)):
                        return True
                except Exception:
                    pass

        return False


    def _sprite_motion_deform_parts_for(tag):
        callback = getattr(config, "sprite_motion_deform_parts_callback", None)

        if callable(callback):
            parts = callback(tag)
            if parts is not None:
                return set([str(part) for part in parts])

        data = getattr(config, "sprite_motion_deform_parts", {}) or {}
        parts = []
        parts.extend(data.get("default", ()))
        parts.extend(data.get(tag, ()))
        return set([str(part) for part in parts])


    def _sprite_motion_deform_mode(part):
        callback = getattr(config, "sprite_motion_deform_mode_callback", None)

        if callable(callback):
            mode = callback(part)
            if mode:
                return str(mode)

        modes = getattr(config, "sprite_motion_deform_part_modes", {}) or {}
        return str(modes.get(str(part), "single"))


    def _sprite_motion_deform_map_name(tag, part, attrs, child_name=None):
        callback = getattr(config, "sprite_motion_deform_map_callback", None)

        if callable(callback):
            value = callback(tag, part, attrs, child_name)
            if value:
                return str(value)

        maps = getattr(config, "sprite_motion_deform_maps", {}) or {}
        attr_key = " ".join([str(attr) for attr in attrs])
        keys = (
            (tag, part, attr_key),
            (tag, part),
            "%s %s %s" % (tag, part, attr_key),
            "%s %s" % (tag, part),
        )

        for key in keys:
            if key in maps:
                return maps[key]

        suffix = _sprite_motion_deform_settings().get("map_suffix", "displace")
        candidates = []

        if child_name:
            child_name = str(child_name)
            candidates.extend([
                "%s_%s" % (child_name, suffix),
                "%s_map" % child_name,
                "%s %s" % (child_name, suffix),
                "%s map" % child_name,
            ])

        candidates.append(" ".join([str(tag), str(part)] + [str(attr) for attr in attrs] + [str(suffix)]))

        for candidate in candidates:
            if _sprite_motion_optional_image_exists(candidate):
                return candidate

        return candidates[-1]


    def _sprite_motion_deform_motion(mode, st, amount):
        settings = _sprite_motion_deform_settings()
        main_intensity = float(settings.get("mainIntensity", settings.get("main_intensity", 55.0))) * float(amount)
        side_intensity = float(settings.get("sideIntensity", settings.get("side_intensity", 15.0))) * float(amount)
        bounce_angle = float(settings.get("bounceAngle", settings.get("bounce_angle", 90.0)))
        bounce_speed = float(settings.get("bounceSpeed", settings.get("bounce_speed", 0.6)))
        damping_factor = float(settings.get("dampingFactor", settings.get("damping_factor", 0.85)))
        min_intensity = float(settings.get("minIntensity", settings.get("min_intensity", 0.1)))
        source_fps = float(settings.get("sourceFps", settings.get("source_fps", 30.0)))

        if main_intensity <= 0.0:
            return None

        bounce_time = -math.pi / 2.0 + (float(st) * source_fps * bounce_speed)
        damping = math.exp(-bounce_time * (1.0 - damping_factor))
        current_intensity = main_intensity * damping

        if current_intensity < min_intensity:
            return None

        angle_rad = (bounce_angle - 90.0) * math.pi / 180.0
        main_move = math.sin(bounce_time) * current_intensity
        side_move = math.cos(bounce_time) * (side_intensity * current_intensity / main_intensity)
        main_x = main_move * math.sin(angle_rad)
        main_y = main_move * math.cos(angle_rad)
        side_x = side_move * math.sin(angle_rad + math.pi / 2.0)
        side_y = side_move * math.cos(angle_rad + math.pi / 2.0)

        if mode == "left":
            return (main_x + side_x, main_y + side_y, 0.0, 0.0), 0.0

        if mode == "right":
            return (main_x - side_x, main_y - side_y, 0.0, 0.0), 0.0

        if mode == "both":
            return (main_x, main_y, side_x, side_y), 1.0

        return (main_x, main_y, 0.0, 0.0), 0.0


    def _sprite_motion_jump_frame_state(st, amount):
        settings = _sprite_motion_jump_settings()
        source_fps = float(settings.get("sourceFps", settings.get("source_fps", 30.0)))
        jump_height = float(settings.get("jumpHeight", settings.get("jump_height", 6.0))) * float(amount)
        jump_speed = float(settings.get("jumpSpeed", settings.get("jump_speed", 3.0)))
        jump_damping = float(settings.get("jumpDamping", settings.get("jump_damping", 0.6)))
        gravity = float(settings.get("gravity", 4.0))
        squash_factor = float(settings.get("squashFactor", settings.get("squash_factor", 0.05)))
        landing_squash_factor = float(settings.get("landingSquashFactor", settings.get("landing_squash_factor", 0.0)))
        squash_interpolation = float(settings.get("squashInterpolation", settings.get("squash_interpolation", 0.25)))
        squash_end_time = float(settings.get("squashEndTime", settings.get("squash_end_time", 0.28)))
        min_velocity_threshold = float(settings.get("minVelocityThreshold", settings.get("min_velocity_threshold", 0.5)))

        if jump_height <= 0.0:
            return 0.0, 1.0, True

        y = 0.0
        velocity = -jump_height * jump_speed
        current_squash = 1.0
        target_squash = 1.0
        frames = max(1, int(float(st) * source_fps) + 1)
        done = False

        for i in range(frames):
            velocity += gravity
            y += velocity
            abs_velocity = abs(velocity)

            if y > 0.0:
                y = 0.0

                if landing_squash_factor > 0.0 and abs_velocity > min_velocity_threshold:
                    target_squash = 1.0 + (abs_velocity / jump_height) * landing_squash_factor
                else:
                    target_squash = 1.0
                    current_squash = 1.0

                velocity = -velocity * jump_damping
            else:
                target_squash = max(1.0 - (abs_velocity / jump_height) * squash_factor, 1.0 - squash_factor)

            current_squash = current_squash + (target_squash - current_squash) * squash_interpolation

            if squash_end_time >= 0.0 and (i + 1) / source_fps >= squash_end_time:
                current_squash = 1.0
                target_squash = 1.0

            if y == 0.0 and abs(velocity) < min_velocity_threshold and abs(current_squash - 1.0) < 0.01:
                done = True
                current_squash = 1.0
                break

        return y, current_squash, done


    def _sprite_motion_nudge_scale_state(st, nudge_motion):
        if nudge_motion is None:
            return 1.0, 1.0, 0.0

        start, end, duration = nudge_motion
        duration = float(duration)

        if duration <= 0.0 or st >= duration:
            return 1.0, 1.0, 0.0

        settings = _sprite_motion_nudge_settings()
        squeeze_factor = float(settings.get("squeezeFactor", settings.get("squeeze_factor", 0.012)))

        if squeeze_factor <= 0.0:
            return 1.0, 1.0, 0.0

        progress = max(0.0, min(1.0, st / duration))
        pulse = math.sin(progress * math.pi)
        distance = abs(float(end) - float(start))
        reference_distance = max(1.0, float(settings.get("distance", 10.0)))
        amount_scale = min(1.5, distance / reference_distance)
        squeeze = squeeze_factor * amount_scale * pulse

        return 1.0 + squeeze, 1.0 - squeeze, float(settings.get("squeezeYOffset", settings.get("squeeze_yoffset", 0.0))) * squeeze


    def _sprite_motion_parts_from_raw(raw):
        if isinstance(raw, dict):
            base = raw.get("base", None)
            overlays = raw.get("overlays", [])
            parts = raw.get("parts", None)

            if parts is not None:
                return list(parts)

            if base:
                return [base] + list(overlays)

            return list(overlays)

        return list(raw)


    def _sprite_motion_layer_config(tag, attrs):
        callback = getattr(config, "sprite_motion_layered_parts_callback", None)

        if callable(callback):
            parts = callback(tag, attrs)
            if parts is not None:
                return _sprite_motion_parts_from_raw(parts)

        data = getattr(config, "sprite_motion_layered_sprites", {}) or {}
        raw = data.get(tag, {})

        if isinstance(raw, dict):
            attr_key = " ".join([str(attr) for attr in attrs])

            if attr_key and attr_key in raw:
                return _sprite_motion_parts_from_raw(raw[attr_key])

            if attrs and attrs[0] in raw:
                return _sprite_motion_parts_from_raw(raw[attrs[0]])

            for fallback_key in ("default", "*"):
                if fallback_key in raw:
                    return _sprite_motion_parts_from_raw(raw[fallback_key])

            if "parts" in raw or "base" in raw or "overlays" in raw:
                return _sprite_motion_parts_from_raw(raw)

            return []

        return _sprite_motion_parts_from_raw(raw)


    def _sprite_motion_part_name_and_image(tag, part, attrs):
        if isinstance(part, dict):
            part_name = part.get("part", part.get("name", ""))
            image_name = part.get("image", None)

            if image_name:
                return str(part_name), str(image_name)

            part = part_name

        return str(part), " ".join([tag, str(part)] + list(attrs))


    def _sprite_motion_deform_displayable(tag, part, attrs, child_name, amount):
        if amount is None:
            return renpy.displayable(child_name)

        if str(part) not in _sprite_motion_deform_parts_for(tag):
            return renpy.displayable(child_name)

        map_name = _sprite_motion_deform_map_name(tag, part, attrs, child_name)

        if not _sprite_motion_optional_image_exists(map_name):
            return renpy.displayable(child_name)

        mode = _sprite_motion_deform_mode(part)
        return SpriteDeformPart(child_name, map_name, mode, amount)


    def _sprite_motion_composite_size():
        size = getattr(config, "sprite_motion_composite_size", None)

        if size:
            return tuple(size)

        return (int(config.screen_width), int(config.screen_height))


    def _sprite_motion_resolve_image_name(tag, attrs, layer):
        callback = getattr(config, "sprite_motion_image_name_callback", None)

        if callable(callback):
            value = callback(tag, attrs, layer)
            if value:
                return str(value)

        return " ".join([tag] + list(attrs))


    def _sprite_motion_apply(tag, jump_amount=None, nudge_motion=None, deform_amount=None):
        layer = _sprite_motion_layer(tag)

        callback = getattr(config, "sprite_motion_apply_callback", None)
        if callable(callback):
            handled = callback(tag, layer, jump_amount, nudge_motion, deform_amount)
            if handled:
                return True

        if not _sprite_motion_showing(tag, layer):
            return False

        try:
            attrs = tuple(renpy.get_attributes(tag, layer=layer) or ())
        except Exception:
            attrs = ()

        _sprite_motion_store_facing(tag, attrs)

        nudge_offset = _sprite_motion_offset(tag)
        parts = _sprite_motion_layer_config(tag, attrs)
        displayable = None

        if parts:
            composite_args = []

            for part in parts:
                part_name, image_name = _sprite_motion_part_name_and_image(tag, part, attrs)
                child = _sprite_motion_deform_displayable(tag, part_name, attrs, image_name, deform_amount)
                composite_args.extend([(0, 0), child])

            displayable = renpy.store.Composite(_sprite_motion_composite_size(), *composite_args)
            image_name = tag
        else:
            image_name = _sprite_motion_resolve_image_name(tag, attrs, layer)

        at_list = [
            sprite_motion_overlay(
                jump_amount=jump_amount,
                nudge_offset=nudge_offset,
                nudge_motion=nudge_motion,
            )
        ]

        kwargs = dict(layer=layer, tag=tag, at_list=at_list)

        if displayable is not None:
            kwargs["what"] = displayable

        renpy.show(image_name, **kwargs)
        return True


    def sprite_motion_apply_nudge(tag, direction=None, amount=1.0, automatic=False, pause=False):
        if not _sprite_motion_showing(tag):
            return False

        start, end = _sprite_motion_nudge_targets(tag, direction, amount, automatic)
        settings = _sprite_motion_nudge_settings()
        duration = float(settings.get("duration", 0.18))
        deform_amount = float(settings.get("deformAmount", settings.get("deform_amount", 0.0))) * float(amount)

        if not _sprite_motion_apply(tag, nudge_motion=(start, end, duration), deform_amount=deform_amount):
            _sprite_motion_set_offset(tag, start)
            return False

        if pause:
            renpy.pause(duration, hard=False)

        return True


    def _sprite_motion_dialogue_callback(event, interact=True, **kwargs):
        if event != "begin" or not interact:
            return

        if not getattr(config, "sprite_motion_auto_nudge", False):
            return

        callback = getattr(config, "sprite_motion_auto_nudge_tag_callback", None)

        if callable(callback):
            tag = callback(event, interact, kwargs)
        else:
            try:
                tag = renpy.get_say_image_tag()
            except Exception:
                tag = None

        if not tag:
            return

        tag = str(tag)

        if _sprite_motion_consume_auto_nudge_suppression(tag):
            return

        sprite_motion_apply_nudge(tag, automatic=True)


    if _sprite_motion_dialogue_callback not in config.all_character_callbacks:
        config.all_character_callbacks.append(_sprite_motion_dialogue_callback)


    def _depth_background_default_settings():
        defaults = {
            "base_depth_suffix": "depth",
            "foreground_suffix": "foreground",
            "foreground_depth_suffix": "foreground_depth",
            "video_suffix": "depth_packed",
            "videoPackedWidth": 2560,
            "videoPackedHeight": 720,
            "backgroundStrength": 40.0,
            "videoStrength": 40.0,
            "foregroundStrength": 20.0,
            "default_mode": "auto",
            "driftSpeed": 0.16,
            "driftRadiusX": 0.25,
            "driftRadiusY": 0.16,
            "mouseRadiusX": 0.35,
            "mouseRadiusY": 0.25,
            "mouseIdleSeconds": 2.0,
            "mouseMoveThreshold": 1.0,
            "motionBlendSpeed": 1.8,
            "sprite_parallax_default": False,
            "sprite_parallax_default_strength": 6.0,
            "clear_layer": True,
        }
        defaults.update(getattr(config, "depth_background_settings", {}) or {})
        return defaults


    def _depth_background_settings():
        return _depth_background_default_settings()


    def _depth_background_effective_mode(requested_mode):
        requested_mode = requested_mode or "auto"

        callback = getattr(config, "depth_background_mode_callback", None)

        if callable(callback):
            mode = callback(requested_mode)
            if mode:
                return str(mode)

        return requested_mode


    def _depth_background_layer():
        return getattr(config, "depth_background_layer", "master")


    def _depth_background_tag():
        return getattr(config, "depth_background_tag", "_depth_background")


    def _depth_optional_name(base_name, suffix):
        callback = getattr(config, "depth_background_image_name_callback", None)

        if callable(callback):
            value = callback(base_name, suffix)
            if value:
                return str(value)

        candidates = [
            "%s_%s" % (base_name, suffix),
            "%s %s" % (base_name, suffix),
        ]

        for candidate in candidates:
            if _sprite_motion_optional_image_exists(candidate):
                return candidate

        return None


    def _depth_video_path(base_name):
        callback = getattr(config, "depth_background_video_path_callback", None)

        if callable(callback):
            value = callback(base_name)
            if value:
                return str(value)

        name = str(base_name)
        settings = _depth_background_settings()
        suffix = settings.get("video_suffix", "depth_packed")
        candidates = [name]

        if not name.endswith((".webm", ".mp4")):
            candidates.extend([
                "%s.webm" % name,
                "%s.mp4" % name,
                "%s_%s.webm" % (name, suffix),
                "%s_%s.mp4" % (name, suffix),
            ])

        for candidate in candidates:
            for prefix in ("", "images/"):
                path = "%s%s" % (prefix, candidate)
                try:
                    if renpy.loadable(path):
                        return path
                except Exception:
                    pass

        return None


    def _depth_background_showing():
        try:
            return renpy.showing(_depth_background_tag(), layer=_depth_background_layer())
        except Exception:
            return bool(getattr(renpy.store, "_depth_background_motion_active", False))


    def _depth_background_reset_offsets():
        renpy.store._depth_background_offset_x = 0.0
        renpy.store._depth_background_offset_y = 0.0
        renpy.store._depth_background_motion_active = False
        renpy.store._depth_background_sprite_parallax_enabled = False


    def _sprite_motion_reset_state():
        state = _sprite_motion_state()
        state.setdefault("offsets", {}).clear()
        state.setdefault("counts", {}).clear()
        state.setdefault("pending_direction_signs", {}).clear()


    def _parse_depth_mode_statement(lexer, statement_name):
        name_parts = []
        mode = None
        sprite_parallax = None
        modes = set(["off", "static", "drift", "mouse", "auto"])

        while not lexer.eol():
            word = lexer.word()

            if not word:
                break

            if word in modes:
                mode = word
                continue

            if word in ("depth", "mode"):
                mode_word = lexer.word()

                if mode_word not in modes:
                    lexer.error("%s mode must be off, static, drift, mouse, or auto" % statement_name)

                mode = mode_word
                continue

            if word in ("sprite_parallax", "sprites", "parallax"):
                value = lexer.word()

                if value in ("on", "true", "yes", "1"):
                    sprite_parallax = True
                elif value in ("off", "false", "no", "0"):
                    sprite_parallax = False
                else:
                    lexer.error("%s sprite_parallax must be on or off" % statement_name)

                continue

            name_parts.append(word)

        if not name_parts:
            lexer.error("%s requires a name" % statement_name)

        return " ".join(name_parts), mode, sprite_parallax


    def _parse_depth_background(lexer):
        return _parse_depth_mode_statement(lexer, "depth_background")


    def _parse_depth_video(lexer):
        return _parse_depth_mode_statement(lexer, "depth_video")


    def _show_depth_background(base_name, mode=None, sprite_parallax=None):
        settings = _depth_background_settings()

        if mode is None:
            mode = settings.get("default_mode", "auto")

        mode = _depth_background_effective_mode(mode)

        if sprite_parallax is None:
            sprite_parallax = bool(settings.get("sprite_parallax_default", False))

        depth_background = DepthBackground(base_name, mode)
        motion_active = mode in ("auto", "drift", "mouse") and depth_background.has_depth
        layer = _depth_background_layer()

        renpy.store._depth_background_motion_active = motion_active
        renpy.store._depth_background_sprite_parallax_enabled = bool(sprite_parallax and motion_active)
        renpy.store._depth_background_offset_x = 0.0
        renpy.store._depth_background_offset_y = 0.0
        _sprite_motion_reset_state()

        if settings.get("clear_layer", True):
            renpy.scene(layer=layer)

        renpy.show(
            _depth_background_tag(),
            layer=layer,
            tag=_depth_background_tag(),
            what=depth_background,
        )


    def _execute_depth_background(parsed):
        base_name, mode, sprite_parallax = parsed
        _show_depth_background(base_name, mode, sprite_parallax)


    def _execute_depth_video(parsed):
        base_name, mode, sprite_parallax = parsed
        settings = _depth_background_settings()

        if mode is None:
            mode = settings.get("default_mode", "auto")

        mode = _depth_background_effective_mode(mode)

        if sprite_parallax is None:
            sprite_parallax = bool(settings.get("sprite_parallax_default", False))

        video_path = _depth_video_path(base_name)

        if not video_path:
            raise Exception("depth_video could not find a loadable packed video for '%s'." % base_name)

        motion_active = mode in ("auto", "drift", "mouse")
        layer = _depth_background_layer()
        renpy.store._depth_background_motion_active = motion_active
        renpy.store._depth_background_sprite_parallax_enabled = bool(sprite_parallax and motion_active)
        renpy.store._depth_background_offset_x = 0.0
        renpy.store._depth_background_offset_y = 0.0
        _sprite_motion_reset_state()

        if settings.get("clear_layer", True):
            renpy.scene(layer=layer)

        safe_channel = str(base_name).replace("/", "_").replace("\\", "_").replace(".", "_").replace(" ", "_")
        movie = renpy.store.Movie(
            play=video_path,
            loop=True,
            channel="_depth_video_%s" % safe_channel,
            size=(
                int(settings.get("videoPackedWidth", settings.get("video_packed_width", 2560))),
                int(settings.get("videoPackedHeight", settings.get("video_packed_height", 720))),
            ),
        )
        depth_video = renpy.store.Transform(
            movie,
            xysize=(int(config.screen_width), int(config.screen_height)),
            fit="fill",
            mesh=True,
            shader="renpy.depth_video_packed_displace",
            u_depth_background_offset=(0.0, 0.0),
            function=DepthVideoMotion(mode, float(settings.get("videoStrength", settings.get("video_strength", 40.0)))),
        )
        renpy.show(
            _depth_background_tag(),
            layer=layer,
            tag=_depth_background_tag(),
            what=depth_video,
        )


    def _parse_nudge(lexer):
        tag = lexer.word()

        if tag is None:
            lexer.error("nudge requires an image tag, e.g. nudge eileen left 0.5")

        direction = None
        amount = 1.0

        if not lexer.eol():
            word = lexer.word()

            if word in ("left", "right"):
                direction = word

                if not lexer.eol():
                    raw_amount = lexer.rest().strip()

                    try:
                        amount = float(raw_amount)
                    except Exception:
                        lexer.error("nudge amount must be a number, e.g. nudge eileen right 0.5")
            else:
                try:
                    amount = float(word)
                except Exception:
                    lexer.error("nudge direction must be left/right or the amount must be a number")

                if not lexer.eol():
                    lexer.error("nudge amount should be a single number, e.g. nudge eileen 0.5")

        return tag, direction, max(0.0, amount)


    def _execute_nudge(parsed):
        tag, direction, amount = parsed
        sprite_motion_suppress_next_auto_nudge(tag)
        sprite_motion_apply_nudge(tag, direction=direction, amount=amount, pause=True)


    def _parse_spr_jump(lexer):
        tag = lexer.word()

        if tag is None:
            lexer.error("spr_jump requires an image tag, e.g. spr_jump eileen")

        amount = 1.0

        if not lexer.eol():
            raw_amount = lexer.rest().strip()

            try:
                amount = float(raw_amount)
            except Exception:
                lexer.error("spr_jump amount must be a number, e.g. spr_jump eileen 0.5")

        return tag, max(0.0, amount)


    def _execute_spr_jump(parsed):
        tag, amount = parsed
        deform_amount = amount * float(_sprite_motion_jump_settings().get("deformAmount", _sprite_motion_jump_settings().get("deform_amount", 1.0)))

        if _sprite_motion_apply(tag, jump_amount=amount, deform_amount=deform_amount):
            sprite_motion_suppress_next_auto_nudge(tag)
            renpy.pause(float(_sprite_motion_jump_settings().get("pause", 0.20)), hard=False)


    renpy.register_statement(
        "spr_jump",
        parse=_parse_spr_jump,
        execute=_execute_spr_jump,
    )


    renpy.register_statement(
        "nudge",
        parse=_parse_nudge,
        execute=_execute_nudge,
    )


    renpy.register_statement(
        "depth_background",
        parse=_parse_depth_background,
        execute=_execute_depth_background,
    )


    renpy.register_statement(
        "depth_video",
        parse=_parse_depth_video,
        execute=_execute_depth_video,
    )


default _depth_background_offset_x = 0.0
default _depth_background_offset_y = 0.0
default _depth_background_motion_active = False
default _depth_background_sprite_parallax_enabled = False


init -2 python:
    renpy.register_shader("renpy.sprite_deform_displace", variables="""
        uniform sampler2D tex0;
        uniform sampler2D u_sprite_deform_map;
        uniform vec4 u_sprite_deform_motion;
        uniform float u_sprite_deform_combined;
        uniform float u_sprite_deform_split_center;
        varying vec2 v_tex_coord;
        uniform vec2 res0;
    """, fragment_300="""
        vec4 map_color = texture2D(u_sprite_deform_map, v_tex_coord);
        vec2 scale = u_sprite_deform_motion.xy;
        vec2 map_rb = map_color.rb;
        float influence = map_color.a;

        if (map_color.a > 0.001) {
            map_rb = map_rb / map_color.a;
        }

        if (map_color.a <= 0.001 && (map_color.r > 0.001 || map_color.g > 0.001 || map_color.b > 0.001)) {
            influence = 1.0;
        }

        if (u_sprite_deform_combined > 0.5) {
            float side_sign = 1.0;

            if (v_tex_coord.x >= u_sprite_deform_split_center) {
                side_sign = -1.0;
            }

            scale += u_sprite_deform_motion.zw * vec2(side_sign, side_sign);
        }

        vec2 displacement = (map_rb - vec2(0.5, 0.5)) * scale * influence;
        vec2 uv = clamp(v_tex_coord - displacement / res0, vec2(0.0, 0.0), vec2(1.0, 1.0));

        gl_FragColor = texture2D(tex0, uv);
    """)


    renpy.register_shader("renpy.depth_background_displace", variables="""
        uniform sampler2D tex0;
        uniform sampler2D u_depth_background_map;
        uniform vec2 u_depth_background_offset;
        varying vec2 v_tex_coord;
        uniform vec2 res0;
    """, fragment_300="""
        vec4 map_color = texture2D(u_depth_background_map, v_tex_coord);
        float depth = map_color.r;
        vec2 displacement = depth * u_depth_background_offset;
        vec2 uv = clamp(v_tex_coord - displacement / res0, vec2(0.0, 0.0), vec2(1.0, 1.0));

        gl_FragColor = texture2D(tex0, uv);
    """)


    renpy.register_shader("renpy.depth_video_packed_displace", variables="""
        uniform sampler2D tex0;
        uniform vec2 u_depth_background_offset;
        varying vec2 v_tex_coord;
        uniform vec2 res0;
    """, fragment_300="""
        float half_texel_x = 0.5 / res0.x;
        vec2 depth_coord = vec2(mix(0.5 + half_texel_x, 1.0 - half_texel_x, v_tex_coord.x), v_tex_coord.y);
        float depth = texture2D(tex0, depth_coord).r;
        vec2 displacement = depth * u_depth_background_offset;
        vec2 uv = clamp(v_tex_coord - displacement / res0, vec2(0.0, 0.0), vec2(1.0, 1.0));
        vec2 color_coord = vec2(mix(half_texel_x, 0.5 - half_texel_x, uv.x), uv.y);

        gl_FragColor = texture2D(tex0, color_coord);
    """)


    class SpriteDeformPart(renpy.Displayable):
        def __init__(self, child_name, map_name, mode, amount=1.0, **properties):
            super(SpriteDeformPart, self).__init__(**properties)
            self.child_name = child_name
            self.map_name = map_name
            self.mode = mode
            self.amount = amount

        def render(self, width, height, st, at):
            motion_data = _sprite_motion_deform_motion(self.mode, st, self.amount)

            if motion_data is None:
                child = renpy.displayable(self.child_name)
            else:
                motion, combined = motion_data
                split_center = float(_sprite_motion_deform_settings().get("split_center", 0.5))
                child = renpy.store.Transform(
                    renpy.displayable(self.child_name),
                    mesh=True,
                    shader="renpy.sprite_deform_displace",
                    u_sprite_deform_map=renpy.displayable(self.map_name),
                    u_sprite_deform_motion=motion,
                    u_sprite_deform_combined=combined,
                    u_sprite_deform_split_center=split_center,
                )

                renpy.redraw(self, 0)

            child_render = renpy.render(child, width, height, st, at)
            render = renpy.Render(*child_render.get_size())
            render.blit(child_render, (0, 0))
            return render

        def visit(self):
            children = [renpy.displayable(self.child_name)]

            if _sprite_motion_optional_image_exists(self.map_name):
                children.append(renpy.displayable(self.map_name))

            return children


    class SpriteMotionOverlay(object):
        def __init__(self, jump_amount=None, nudge_offset=0.0, nudge_motion=None):
            self.jump_amount = jump_amount
            self.nudge_offset = float(nudge_offset or 0.0)
            self.nudge_motion = nudge_motion

        def _nudge_offset(self, st):
            if self.nudge_motion is None:
                return self.nudge_offset, True

            start, end, duration = self.nudge_motion
            start = float(start)
            end = float(end)
            duration = float(duration)

            if duration <= 0.0 or st >= duration:
                return end, True

            progress = max(0.0, min(1.0, st / duration))
            eased = 1.0 - ((1.0 - progress) * (1.0 - progress))
            return start + (end - start) * eased, False

        def __call__(self, trans, st, at):
            if not hasattr(trans, "_sprite_motion_base_state"):
                current_motion_x = self.nudge_offset

                if self.nudge_motion is not None:
                    current_motion_x = float(self.nudge_motion[0])

                trans._sprite_motion_base_state = (
                    float(getattr(trans, "xoffset", 0.0) or 0.0) - float(current_motion_x or 0.0),
                    float(getattr(trans, "yoffset", 0.0) or 0.0),
                    float(getattr(trans, "xzoom", 1.0) or 1.0),
                    float(getattr(trans, "yzoom", 1.0) or 1.0),
                )

            base_xoffset, base_yoffset, base_xzoom, base_yzoom = trans._sprite_motion_base_state
            xoffset = 0.0
            yoffset = 0.0
            nudge_x, nudge_done = self._nudge_offset(st)
            jump_done = True
            nudge_xzoom, nudge_yzoom, nudge_yoffset = _sprite_motion_nudge_scale_state(st, self.nudge_motion)

            xoffset += nudge_x
            yoffset += nudge_yoffset

            if self.jump_amount is not None:
                jump_y, xzoom, jump_done = _sprite_motion_jump_frame_state(st, self.jump_amount)
                yoffset += jump_y
                trans.xzoom = base_xzoom * xzoom * nudge_xzoom
                trans.yzoom = base_yzoom * nudge_yzoom
            else:
                trans.xzoom = base_xzoom * nudge_xzoom
                trans.yzoom = base_yzoom * nudge_yzoom

            trans.xoffset = base_xoffset + xoffset
            trans.yoffset = base_yoffset + yoffset

            if not nudge_done or not jump_done:
                return 0

            trans.xzoom = base_xzoom
            trans.yzoom = base_yzoom
            trans.xoffset = base_xoffset + nudge_x
            trans.yoffset = base_yoffset

            return None


    class DepthBackgroundParallax(object):
        def __init__(self, strength=6.0):
            self.strength = float(strength)

        def __call__(self, trans, st, at):
            if not getattr(renpy.store, "_depth_background_motion_active", False):
                trans.xoffset = 0
                trans.yoffset = 0
                return None

            if not _depth_background_showing():
                trans.xoffset = 0
                trans.yoffset = 0
                return None

            if not getattr(renpy.store, "_depth_background_sprite_parallax_enabled", False):
                trans.xoffset = 0
                trans.yoffset = 0
                return None

            offset_x = float(getattr(renpy.store, "_depth_background_offset_x", 0.0))
            offset_y = float(getattr(renpy.store, "_depth_background_offset_y", 0.0))
            trans.xoffset = offset_x * self.strength
            trans.yoffset = offset_y * self.strength
            return 0


    class DepthVideoMotion(object):
        def __init__(self, mode="static", strength=40.0):
            self.mode = mode or "static"
            self.strength = float(strength)
            self.current_offset = None
            self.last_st = None
            self.last_mouse_pos = None
            self.last_mouse_motion_st = -999.0

        def _drift_offset(self, st):
            settings = _depth_background_settings()
            speed = float(settings.get("driftSpeed", settings.get("drift_speed", 0.16)))
            radius_x = float(settings.get("driftRadiusX", settings.get("drift_radius_x", 0.25)))
            radius_y = float(settings.get("driftRadiusY", settings.get("drift_radius_y", 0.16)))
            return math.sin(st * speed) * radius_x, math.cos(st * speed) * radius_y

        def _mouse_offset(self):
            settings = _depth_background_settings()

            try:
                mouse_x, mouse_y = renpy.get_mouse_pos()
                screen_w = float(config.screen_width)
                screen_h = float(config.screen_height)
                radius_x = float(settings.get("mouseRadiusX", settings.get("mouse_radius_x", 0.35)))
                radius_y = float(settings.get("mouseRadiusY", settings.get("mouse_radius_y", 0.25)))

                if screen_w <= 0.0 or screen_h <= 0.0:
                    return 0.0, 0.0, None

                return (
                    ((float(mouse_x) - screen_w / 2.0) / (screen_w / 2.0)) * radius_x,
                    ((float(mouse_y) - screen_h / 2.0) / (screen_h / 2.0)) * radius_y,
                    (float(mouse_x), float(mouse_y)),
                )
            except Exception:
                return 0.0, 0.0, None

        def _mouse_recently_moved(self, st, mouse_pos):
            if mouse_pos is None:
                return False

            settings = _depth_background_settings()
            threshold = float(settings.get("mouseMoveThreshold", settings.get("mouse_move_threshold", 1.0)))
            idle_seconds = float(settings.get("mouseIdleSeconds", settings.get("mouse_idle_seconds", 2.0)))

            if self.last_mouse_pos is None:
                self.last_mouse_pos = mouse_pos
                return False

            dx = mouse_pos[0] - self.last_mouse_pos[0]
            dy = mouse_pos[1] - self.last_mouse_pos[1]
            self.last_mouse_pos = mouse_pos

            if (dx * dx + dy * dy) ** 0.5 >= threshold:
                self.last_mouse_motion_st = st

            return (st - self.last_mouse_motion_st) <= idle_seconds

        def _offset(self, st):
            live_mode = _depth_background_effective_mode(self.mode)

            if live_mode in ("off", "static"):
                self.current_offset = (0.0, 0.0)
                self.last_st = st
                return 0.0, 0.0

            mouse_x, mouse_y, mouse_pos = self._mouse_offset()
            drift_x, drift_y = self._drift_offset(st)

            if live_mode == "mouse":
                target_x, target_y = mouse_x, mouse_y
            elif live_mode == "auto":
                if self._mouse_recently_moved(st, mouse_pos):
                    target_x, target_y = mouse_x, mouse_y
                else:
                    target_x, target_y = drift_x, drift_y
            else:
                target_x, target_y = drift_x, drift_y

            if self.current_offset is None or self.last_st is None:
                self.current_offset = (target_x, target_y)
            else:
                settings = _depth_background_settings()
                blend_speed = float(settings.get("motionBlendSpeed", settings.get("motion_blend_speed", 1.8)))
                dt = max(0.0, st - self.last_st)
                alpha = min(1.0, dt * blend_speed)
                current_x, current_y = self.current_offset
                self.current_offset = (
                    current_x + (target_x - current_x) * alpha,
                    current_y + (target_y - current_y) * alpha,
                )

            self.last_st = st
            return self.current_offset

        def __call__(self, trans, st, at):
            offset_x, offset_y = self._offset(st)
            renpy.store._depth_background_offset_x = offset_x
            renpy.store._depth_background_offset_y = offset_y
            trans.u_depth_background_offset = (offset_x * self.strength, offset_y * self.strength)

            if self.mode in ("auto", "drift", "mouse"):
                return 0

            return None


    class DepthBackground(renpy.Displayable):
        def __init__(self, base_name, mode="static", **properties):
            super(DepthBackground, self).__init__(**properties)
            self.base_name = base_name
            self.mode = mode or "static"
            self.current_offset = None
            self.last_st = None
            self.last_mouse_pos = None
            self.last_mouse_motion_st = -999.0

            settings = _depth_background_settings()
            self.base_depth_name = _depth_optional_name(base_name, settings.get("base_depth_suffix", "depth"))
            self.foreground_name = _depth_optional_name(base_name, settings.get("foreground_suffix", "foreground"))
            self.foreground_depth_name = _depth_optional_name(base_name, settings.get("foreground_depth_suffix", "foreground_depth"))
            self.has_depth = bool(self.base_depth_name or (self.foreground_name and self.foreground_depth_name))

        def _screen_size(self):
            return int(config.screen_width), int(config.screen_height)

        def _cover_displayable(self, image_name):
            return renpy.store.Transform(
                renpy.displayable(image_name),
                xysize=self._screen_size(),
                fit="cover",
                xalign=0.5,
                yalign=0.5,
            )

        def _drift_offset(self, st):
            return DepthVideoMotion(self.mode)._drift_offset(st)

        def _mouse_offset(self):
            return DepthVideoMotion(self.mode)._mouse_offset()

        def _mouse_recently_moved(self, st, mouse_pos):
            if mouse_pos is None:
                return False

            settings = _depth_background_settings()
            threshold = float(settings.get("mouseMoveThreshold", settings.get("mouse_move_threshold", 1.0)))
            idle_seconds = float(settings.get("mouseIdleSeconds", settings.get("mouse_idle_seconds", 2.0)))

            if self.last_mouse_pos is None:
                self.last_mouse_pos = mouse_pos
                return False

            dx = mouse_pos[0] - self.last_mouse_pos[0]
            dy = mouse_pos[1] - self.last_mouse_pos[1]
            self.last_mouse_pos = mouse_pos

            if (dx * dx + dy * dy) ** 0.5 >= threshold:
                self.last_mouse_motion_st = st

            return (st - self.last_mouse_motion_st) <= idle_seconds

        def _offset(self, st):
            motion = DepthVideoMotion(self.mode)
            motion.current_offset = self.current_offset
            motion.last_st = self.last_st
            motion.last_mouse_pos = self.last_mouse_pos
            motion.last_mouse_motion_st = self.last_mouse_motion_st
            offset = motion._offset(st)
            self.current_offset = motion.current_offset
            self.last_st = motion.last_st
            self.last_mouse_pos = motion.last_mouse_pos
            self.last_mouse_motion_st = motion.last_mouse_motion_st
            return offset

        def _layer_displayable(self, image_name, depth_name, strength, offset_x, offset_y):
            if self.mode in ("off", "static") or not depth_name:
                return self._cover_displayable(image_name)

            return renpy.store.Transform(
                self._cover_displayable(image_name),
                mesh=True,
                shader="renpy.depth_background_displace",
                u_depth_background_map=self._cover_displayable(depth_name),
                u_depth_background_offset=(offset_x * strength, offset_y * strength),
            )

        def render(self, width, height, st, at):
            settings = _depth_background_settings()
            offset_x, offset_y = self._offset(st)
            background_strength = float(settings.get("backgroundStrength", settings.get("background_strength", 40.0)))

            renpy.store._depth_background_offset_x = offset_x
            renpy.store._depth_background_offset_y = offset_y

            children = [
                self._layer_displayable(
                    self.base_name,
                    self.base_depth_name,
                    background_strength,
                    offset_x,
                    offset_y,
                )
            ]

            if self.foreground_name:
                children.append(
                    self._layer_displayable(
                        self.foreground_name,
                        self.foreground_depth_name,
                        float(settings.get("foregroundStrength", settings.get("foreground_strength", 20.0))),
                        offset_x,
                        offset_y,
                    )
                )

            composite = renpy.store.Fixed(*children)
            composite_render = renpy.render(composite, width, height, st, at)
            render = renpy.Render(*composite_render.get_size())
            render.blit(composite_render, (0, 0))

            if self.mode in ("auto", "drift", "mouse") and self.has_depth:
                renpy.redraw(self, 0)

            return render

        def visit(self):
            children = [renpy.displayable(self.base_name)]

            for image_name in (self.base_depth_name, self.foreground_name, self.foreground_depth_name):
                if image_name:
                    children.append(renpy.displayable(image_name))

            return children


transform sprite_motion_overlay(jump_amount=None, nudge_offset=0.0, nudge_motion=None):
    subpixel True
    function SpriteMotionOverlay(jump_amount, nudge_offset, nudge_motion)


transform depth_background_parallax(strength=6.0):
    subpixel True
    function DepthBackgroundParallax(strength)
