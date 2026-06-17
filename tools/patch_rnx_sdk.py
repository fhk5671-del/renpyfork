from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK = Path(r"C:\Users\super\Dropbox\renpy-8.4.1-rnx-sdk")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def replace(path: Path, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise RuntimeError(f"Expected text not found in {path}")
    write(path, text.replace(old, new, 1))


def replace_all(path: Path, replacements: list[tuple[str, str]]) -> None:
    text = read(path)
    for old, new in replacements:
        if old not in text:
            raise RuntimeError(f"Expected text not found in {path}:\n{old[:200]}")
        text = text.replace(old, new, 1)
    write(path, text)


def copy_feature_files(sdk: Path) -> None:
    for rel in [
        "renpy/common/00motion_depth.rpy",
        "renpy/common/00voice_manifest.rpy",
        "renpy/translation/voice_manifest.py",
    ]:
        src = ROOT / rel
        dst = sdk / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch a Ren'Py 8.4.1 SDK with this fork's RNX/RSC/RSM format support.")
    parser.add_argument("--sdk", type=Path, default=DEFAULT_SDK, help="Path to the SDK root to patch.")
    args = parser.parse_args()

    SDK = args.sdk.resolve()

    if not SDK.exists():
        raise RuntimeError(f"SDK copy does not exist: {SDK}")

    shutil.copy2(ROOT / "renpy" / "custom_format.py", SDK / "renpy" / "custom_format.py")
    copy_feature_files(SDK)

    init_py = SDK / "renpy" / "__init__.py"
    replace(init_py, "    import renpy.translation.dialogue\n", "    import renpy.translation.dialogue\n    import renpy.translation.voice_manifest\n")

    loader = SDK / "renpy" / "loader.py"
    replace(loader, "import renpy\n", "import renpy\nimport renpy.custom_format as custom_format\n")
    replace(
        loader,
        """class RPAv3ArchiveHandler(object):
    \"\"\"
    Archive handler handling RPAv3 archives.
    \"\"\"

    archive_extension = \".rpa\"

    @staticmethod
    def get_supported_extensions():
        return [\".rpa\"]

    @staticmethod
    def get_supported_headers():
        return [b\"RPA-3.0 \"]

    @staticmethod
    def read_index(infile):
        l = infile.read(40)
        offset = int(l[8:24], 16)
        key = int(l[25:33], 16)
        infile.seek(offset)
        index = loads(zlib.decompress(infile.read()))

        def start_to_bytes(s):
            if not s:
                return b\"\"

            if not isinstance(s, bytes):
                s = s.encode(\"latin-1\")

            return s

        # Deobfuscate the index.

        for k in index.keys():
            if len(index[k][0]) == 2:
                index[k] = [(offset ^ key, dlen ^ key) for offset, dlen in index[k]]
            else:
                index[k] = [(offset ^ key, dlen ^ key, start_to_bytes(start)) for offset, dlen, start in index[k]]

        return index


archive_handlers.append(RPAv3ArchiveHandler)


class RPAv2ArchiveHandler(object):
    \"\"\"
    Archive handler handling RPAv2 archives.
    \"\"\"

    archive_extension = \".rpa\"

    @staticmethod
    def get_supported_extensions():
        return [\".rpa\"]

    @staticmethod
    def get_supported_headers():
        return [b\"RPA-2.0 \"]

    @staticmethod
    def read_index(infile):
        l = infile.read(24)
        offset = int(l[8:], 16)
        infile.seek(offset)
        index = loads(zlib.decompress(infile.read()))

        return index


archive_handlers.append(RPAv2ArchiveHandler)


class RPAv1ArchiveHandler(object):
    \"\"\"
    Archive handler handling RPAv1 archives.
    \"\"\"

    archive_extension = \".rpa\"

    @staticmethod
    def get_supported_extensions():
        return [\".rpi\"]

    @staticmethod
    def get_supported_headers():
        return [b\"\\x78\\x9c\"]

    @staticmethod
    def read_index(infile):
        return loads(zlib.decompress(infile.read()))


archive_handlers.append(RPAv1ArchiveHandler)
""",
        """class RNXArchiveHandler(object):
    \"\"\"
    Archive handler handling this fork's RNX archives.
    \"\"\"

    archive_extension = custom_format.ARCHIVE_EXTENSION

    @staticmethod
    def get_supported_extensions():
        return [custom_format.ARCHIVE_EXTENSION]

    @staticmethod
    def get_supported_headers():
        return [custom_format.ARCHIVE_MAGIC]

    @staticmethod
    def read_index(infile):
        l = infile.read(len(custom_format.ARCHIVE_HEADER_PLACEHOLDER))
        offset = int(l[8:24], 16)
        length = int(l[25:41], 16)
        infile.seek(offset)
        return loads(custom_format.open_sealed(infile.read(length), custom_format.ARCHIVE_INDEX_PURPOSE))


archive_handlers.append(RNXArchiveHandler)


# Legacy RPA handlers are intentionally not registered by this fork.
""",
    )
    replace(
        loader,
        """            if len(t) == 2:
                offset, dlen = t
                start = b\"\"
            else:
                offset, dlen, start = t
""",
        """            if len(t) == 2:
                offset, dlen = t
                start = b\"\"
            elif len(t) == 3:
                offset, dlen, _usize = t
                with open(afn, \"rb\") as f:
                    f.seek(offset)
                    member = custom_format.open_sealed(f.read(dlen), custom_format.ARCHIVE_MEMBER_PURPOSE)

                rv = RWopsIO.from_buffer(member, name=name)
                return io.BufferedReader(rv)
            else:
                offset, dlen, start = t
""",
    )

    archiver = SDK / "launcher" / "game" / "archiver.rpy"
    replace_all(
        archiver,
        [
            ("    import zlib\n", "    import renpy.custom_format as custom_format\n"),
            (
                """            # A fixed key minimizes difference between archive versions.
            self.key = 0x42424242

            padding = b\"RPA-3.0 XXXXXXXXXXXXXXXX XXXXXXXX\\n\"
            self.f.write(padding)
""",
                """            self.f.write(custom_format.ARCHIVE_HEADER_PLACEHOLDER)
""",
            ),
            (
                """            with open(path, \"rb\") as df:
                data = df.read()
                dlen = len(data)

            # Pad.
            padding = b\"Made with Ren'Py.\"
            self.f.write(padding)
""",
                """            with open(path, \"rb\") as df:
                data = df.read()
                usize = len(data)
                data = custom_format.seal(data, custom_format.ARCHIVE_MEMBER_PURPOSE)
                dlen = len(data)
""",
            ),
            ("            self.index[name].append((offset ^ self.key, dlen ^ self.key, b\"\"))\n", "            self.index[name].append((offset, dlen, usize))\n"),
            (
                """            indexoff = self.f.tell()

            self.f.write(zlib.compress(dumps(self.index, HIGHEST_PROTOCOL)))

            self.f.seek(0)
            self.f.write(b\"RPA-3.0 %016x %08x\\n\" % (indexoff, self.key))
""",
                """            indexoff = self.f.tell()
            index = custom_format.seal(dumps(self.index, HIGHEST_PROTOCOL), custom_format.ARCHIVE_INDEX_PURPOSE)

            self.f.write(index)

            self.f.seek(0)
            self.f.write(custom_format.ARCHIVE_HEADER % (indexoff, len(index)))
""",
            ),
        ],
    )

    script = SDK / "renpy" / "script.py"
    replace(script, "import renpy\n", "import renpy\nimport renpy.custom_format as custom_format\n")
    replace_all(
        script,
        [
            (
                """# Change this to force a recompile of RPYC files when required, if the .rpy file exists.
RPYC_MAGIC = b\"_2025-07-06\"

# A string at the start of each rpycv2 file.
RPYC2_HEADER = b\"RENPY RPC2\"
""",
                """# Change this to force a recompile of compiled script files when required, if the .rpy file exists.
RPYC_MAGIC = b\"_rnx_2026-06-17\"

# A string at the start of each compiled script file.
RPYC2_HEADER = custom_format.COMPILED_SCRIPT_HEADER

COMPILED_SCRIPT_EXTENSION = custom_format.COMPILED_SCRIPT_EXTENSION
COMPILED_MODULE_EXTENSION = custom_format.COMPILED_MODULE_EXTENSION
""",
            ),
            ("        for i in [\"script_version.txt\", \"script_version.rpy\", \"script_version.rpyc\"]:\n", "        for i in [\"script_version.txt\", \"script_version.rpy\", \"script_version\" + COMPILED_SCRIPT_EXTENSION]:\n"),
            (
                """            elif fn.endswith(\".rpyc\"):
                fn = fn[:-5]
                target = script_files
""",
                """            elif fn.endswith(COMPILED_SCRIPT_EXTENSION):
                fn = fn[: -len(COMPILED_SCRIPT_EXTENSION)]
                target = script_files
""",
            ),
            (
                """            elif fn.endswith(\".rpymc\"):
                fn = fn[:-6]
                target = module_files
""",
                """            elif fn.endswith(COMPILED_MODULE_EXTENSION):
                fn = fn[: -len(COMPILED_MODULE_EXTENSION)]
                target = module_files
""",
            ),
            ("            self.load_appropriate_file(\".rpyc\", [\"_ren.py\", \".rpy\"], dir, fn, initcode)\n", "            self.load_appropriate_file(COMPILED_SCRIPT_EXTENSION, [\"_ren.py\", \".rpy\"], dir, fn, initcode)\n"),
            ("        self.load_appropriate_file(\".rpymc\", [\".rpym\"], dir, fn, initcode)\n", "        self.load_appropriate_file(COMPILED_MODULE_EXTENSION, [\".rpym\"], dir, fn, initcode)\n"),
            (
                """        # Fix the filename for a renamed .rpyc file.
        if filename is not None:
            filename = renpy.lexer.elide_filename(filename)
            if filename[-1] == \"c\":
                filename = filename[:-1]

            if not all_stmts[0].filename.lower().endswith(filename.lower()):
                filename += \"c\"
""",
                """        # Fix the filename for a renamed compiled script file.
        if filename is not None:
            filename = renpy.lexer.elide_filename(filename)
            source_filename = filename

            if source_filename.endswith(COMPILED_SCRIPT_EXTENSION):
                source_filename = source_filename[: -len(COMPILED_SCRIPT_EXTENSION)] + \".rpy\"
            elif source_filename.endswith(COMPILED_MODULE_EXTENSION):
                source_filename = source_filename[: -len(COMPILED_MODULE_EXTENSION)] + \".rpym\"

            if not all_stmts[0].filename.lower().endswith(source_filename.lower()):
""",
            ),
            ("        data = zlib.compress(data, 3)\n", "        data = custom_format.seal(data, custom_format.COMPILED_SCRIPT_PURPOSE)\n"),
            (
                """        # Legacy path.
        if header_data[: len(RPYC2_HEADER)] != RPYC2_HEADER:
            if slot != 1:
                return None

            f.seek(0)
            data = f.read()

            return zlib.decompress(data)

        # RPYC2 path.
""",
                """        if header_data[: len(RPYC2_HEADER)] != RPYC2_HEADER:
            return None

""",
            ),
            ("        return zlib.decompress(data)\n", "        return custom_format.open_sealed(data, custom_format.COMPILED_SCRIPT_PURPOSE)\n"),
            (
                """                if fn.endswith(\"_ren.py\"):
                    rpycfn = fullfn[:-7] + \".rpyc\"
                    oldrpycfn = olddir + \"/\" + fn[:-7] + \".rpyc\"
                else:
                    rpycfn = fullfn + \"c\"
                    oldrpycfn = olddir + \"/\" + fn + \"c\"
""",
                """                if fn.endswith(\"_ren.py\"):
                    rpycfn = fullfn[:-7] + COMPILED_SCRIPT_EXTENSION
                    oldrpycfn = olddir + \"/\" + fn[:-7] + COMPILED_SCRIPT_EXTENSION
                elif fn.endswith(\".rpym\"):
                    rpycfn = fullfn[:-5] + COMPILED_MODULE_EXTENSION
                    oldrpycfn = olddir + \"/\" + fn[:-5] + COMPILED_MODULE_EXTENSION
                else:
                    rpycfn = fullfn[:-4] + COMPILED_SCRIPT_EXTENSION
                    oldrpycfn = olddir + \"/\" + fn[:-4] + COMPILED_SCRIPT_EXTENSION
""",
            ),
            ("            elif fn.endswith(\".rpyc\") or fn.endswith(\".rpymc\"):\n", "            elif fn.endswith(COMPILED_SCRIPT_EXTENSION) or fn.endswith(COMPILED_MODULE_EXTENSION):\n"),
        ],
    )

    arguments = SDK / "renpy" / "arguments.py"
    replace_all(
        arguments,
        [
            ("            \"--keep-orphan-rpyc\",\n", "            \"--keep-orphan-rsc\",\n"),
            ("            action=\"store_true\",\n            help=\"Prevents the compile command from deleting orphan rpyc files.\",\n", "            action=\"store_true\",\n            dest=\"keep_orphan_rpyc\",\n            help=\"Prevents the compile command from deleting orphan compiled script files.\",\n"),
        ],
    )

    config = SDK / "renpy" / "config.py"
    replace(config, "autoreload_blacklist = [\".rpyc\", \".rpymc\", \".rpyb\", \".pyc\", \".pyo\"]", "autoreload_blacklist = [\".rsc\", \".rsm\", \".rpyb\", \".pyc\", \".pyo\"]")
    replace(
        config,
        """auto_voice_predict_callback: Callable[[str], None] | None = None
\"\"\"
A callback that is called when an auto-voice prediction is made.
These are called with the voice tag of the character.
\"\"\"
""",
        """auto_voice_predict_callback: Callable[[str], None] | None = None
\"\"\"
A callback that is called when an auto-voice prediction is made.
These are called with the voice tag of the character.
\"\"\"

voice_manifest_enabled: bool = False
\"\"\"
If True, enables source-key voice manifest lookup and inline voice-tag filtering.
\"\"\"

voice_manifest_config: str | None = None
\"\"\"
The JSON configuration file used by the voice_manifest command, if any.
\"\"\"

voice_manifest_runtime_lookup: str = "game/audio/voice/manifest/voice_lookup.json"
\"\"\"
The filesystem path the voice_manifest command writes for runtime lookup.
\"\"\"

voice_manifest_lookup: str = "audio/voice/manifest/voice_lookup.json"
\"\"\"
The loadable path read by the runtime voice manifest callback.
\"\"\"

voice_manifest_script_files: list[str] | None = None
voice_manifest_profiles: dict[str, Any] | None = None
voice_manifest_dimensions: dict[str, Any] | None = None
voice_manifest_default_profile: str = "default"
voice_manifest_include_narration: bool = True
voice_manifest_audio_pattern: str = "voice/{voice_id}.ogg"
voice_manifest_audio_lines_dir: str = "game/audio/voice/lines"
voice_manifest_speaker_names: dict[str, str] = {}
voice_manifest_skip_speakers: list[str] | None = None
voice_manifest_tag_pattern: str = r"/([A-Za-z][A-Za-z0-9 _'-]{0,60})/"
voice_manifest_tts_tag_format: str = "[{tag}] "
voice_manifest_display_tag_format: str = ""
voice_manifest_strip_inline_tags: bool = True
voice_manifest_require_loadable: bool = True
voice_manifest_override_voice_statement: bool = False
voice_manifest_renpy_id_fallback: bool = True

voice_manifest_profile_callback: Callable[[dict[str, Any]], str | None] | None = None
voice_manifest_runtime_source_key_callback: Callable[[], str | None] | None = None
voice_manifest_source_key_callback: Callable[[str, int], str | None] | None = None
voice_manifest_hash_callback: Callable[[str, str, str, dict[str, Any]], str] | None = None
voice_manifest_voice_id_callback: Callable[[dict[str, Any], int], str | None] | None = None
voice_manifest_export_audio_path_callback: Callable[[dict[str, Any]], str | None] | None = None
voice_manifest_audio_path_callback: Callable[..., str | None] | None = None
voice_manifest_display_tag_callback: Callable[[str], str | None] | None = None
voice_manifest_tts_tag_callback: Callable[[str], str | None] | None = None
voice_manifest_play_callback: Callable[..., Any] | None = None

sprite_motion_layer: str = "master"
sprite_motion_layer_callback: Callable[[str | None], str | None] | None = None
sprite_motion_apply_callback: Callable[..., Any] | None = None
sprite_motion_image_name_callback: Callable[[str, tuple[str, ...], str], str | None] | None = None
sprite_motion_auto_nudge: bool = False
sprite_motion_auto_nudge_tag_callback: Callable[..., str | None] | None = None
sprite_motion_jump_settings: dict[str, Any] = {}
sprite_motion_nudge_settings: dict[str, Any] = {}
sprite_motion_layered_sprites: dict[str, Any] = {}
sprite_motion_layered_parts_callback: Callable[[str, tuple[str, ...]], Any] | None = None
sprite_motion_composite_size: tuple[int, int] | None = None
sprite_motion_deform_parts: dict[str, list[str]] = {}
sprite_motion_deform_parts_callback: Callable[[str], list[str] | None] | None = None
sprite_motion_deform_part_modes: dict[str, str] = {}
sprite_motion_deform_mode_callback: Callable[[str], str | None] | None = None
sprite_motion_deform_maps: dict[Any, str] = {}
sprite_motion_deform_map_callback: Callable[..., str | None] | None = None
sprite_motion_deform_settings: dict[str, Any] = {}

depth_background_layer: str = "master"
depth_background_tag: str = "_depth_background"
depth_background_settings: dict[str, Any] = {}
depth_background_mode_callback: Callable[[str], str | None] | None = None
depth_background_image_name_callback: Callable[[str, str], str | None] | None = None
depth_background_video_path_callback: Callable[[str], str | None] | None = None
""",
    )

    main_py = SDK / "renpy" / "main.py"
    replace(main_py, "    if renpy.exports.loadable(\"tl/None/common.rpym\") or renpy.exports.loadable(\"tl/None/common.rpymc\"):\n", "    if renpy.exports.loadable(\"tl/None/common.rpym\") or renpy.exports.loadable(\"tl/None/common\" + renpy.script.COMPILED_MODULE_EXTENSION):\n")

    build = SDK / "renpy" / "common" / "00build.rpy"
    replace(build, "    import sys, os\n", "    import sys, os\n    import renpy.custom_format as custom_format\n")
    replace(build, "        ( \"**.rpa\", None),\n", "        ( \"**\" + custom_format.ARCHIVE_EXTENSION, None),\n")
    replace(build, "    ]))\n\n\n    def classify_renpy", "    ]))\n\n    for ext in custom_format.LEGACY_ARTIFACT_EXTENSIONS:\n        renpy_patterns.append((\"**\" + ext, None))\n\n\n    def classify_renpy")
    replace(build, "        If one or more files are classified with `name`, `name`.rpa is\n", "        If one or more files are classified with `name`, `name` plus this fork's archive extension is\n")
    replace(build, "        the secret.rpa archive in the windows builds.\n", "        the secret archive in the windows builds.\n")

    distribute = SDK / "launcher" / "game" / "distribute.rpy"
    replace(distribute, "    import shutil\n", "    import shutil\n    import renpy.custom_format as custom_format\n")
    replace(distribute, "                arcfn = arcname + \".rpa\"\n", "                arcfn = arcname + custom_format.ARCHIVE_EXTENSION\n")
    replace(distribute, "                    (not os.path.exists(os.path.join(self.project.path, \"game\", \"script_version.rpyc\"))):\n", "                    (not os.path.exists(os.path.join(self.project.path, \"game\", \"script_version\" + renpy.script.COMPILED_SCRIPT_EXTENSION))):\n")
    replace(distribute, "            reporter.info(_(\"Recompiling all rpy files into rpyc files...\"))\n            project.launch([ \"compile\", \"--keep-orphan-rpyc\" ], wait=True)\n", "            reporter.info(_(\"Recompiling all script files into compiled script files...\"))\n            project.launch([ \"compile\", \"--keep-orphan-rsc\" ], wait=True)\n")
    replace(distribute, "        files = [\n            fn + \"c\" for fn in project.script_files()\n            if fn.startswith(\"game/\") and project.exists(fn + \"c\")]\n", "        def compiled_script_filename(fn):\n            if fn.endswith(\"_ren.py\"):\n                return fn[:-7] + renpy.script.COMPILED_SCRIPT_EXTENSION\n            elif fn.endswith(\".rpym\"):\n                return fn[:-5] + renpy.script.COMPILED_MODULE_EXTENSION\n            else:\n                return fn[:-4] + renpy.script.COMPILED_SCRIPT_EXTENSION\n\n        files = [\n            compiled_script_filename(fn) for fn in project.script_files()\n            if fn.startswith(\"game/\") and project.exists(compiled_script_filename(fn))]\n")
    replace(distribute, "        ap = renpy.arguments.ArgumentParser(\"Back-ups all rpyc files into old-game directory.\")\n", "        ap = renpy.arguments.ArgumentParser(\"Backs up all compiled script files into old-game directory.\")\n")

    options = SDK / "launcher" / "game" / "options.rpy"
    replace(options, "init python:\n\n    # We're building Ren'Py tonight.", "init python:\n\n    import renpy.custom_format as custom_format\n\n    # We're building Ren'Py tonight.")
    replace(options, "        .pyo, .rpyc, .rpycm, and .rpyb go into binary, everything\n", "        .pyo, compiled script files, and .rpyb go into binary, everything\n")
    replace(options, "        build.classify_renpy(pattern + \"/**.rpyc\", binary)\n        build.classify_renpy(pattern + \"/**.rpymc\", binary)\n", "        build.classify_renpy(pattern + \"/**\" + renpy.script.COMPILED_SCRIPT_EXTENSION, binary)\n        build.classify_renpy(pattern + \"/**\" + renpy.script.COMPILED_MODULE_EXTENSION, binary)\n\n        for ext in custom_format.LEGACY_ARTIFACT_EXTENSIONS:\n            build.classify_renpy(pattern + \"/**\" + ext, None)\n")

    project = SDK / "launcher" / "game" / "project.rpy"
    replace(project, "                    self.launch([\"compile\", \"--keep-orphan-rpyc\" ], wait=True)\n", "                    self.launch([\"compile\", \"--keep-orphan-rsc\" ], wait=True)\n")

    front_page = SDK / "launcher" / "game" / "front_page.rpy"
    replace(front_page, "        interface.processing(_(\"Recompiling all rpy files into rpyc files...\"))\n", "        interface.processing(_(\"Recompiling all script files into compiled script files...\"))\n")

    update = SDK / "renpy" / "update" / "update.py"
    replace(update, """    def write_padding(self):
        \"\"\"
        Writes a file containing the padding for RPAs, so it's
        not necessary to download a block file just for that.
        \"\"\"

        padding = b\"Made with Ren'Py.\"

        fn = os.path.join(self.targetdir, \"_padding.old.rpa\")
        with open(fn, \"wb\") as f:
            f.write(padding)

        f = common.File(\"_padding.old.rpa\", data_filename=fn)
        self.old_files.append(f)
""", """    def write_padding(self):
        \"\"\"
        This fork's custom archives do not write shared plaintext padding.
        \"\"\"
        return
""")

    exports = SDK / "renpy" / "exports" / "scriptexports.py"
    replace(exports, "    name.rpym or name.rpymc. If a .rpym file exists, and is newer than the\n    corresponding .rpymc file, it is loaded and a new .rpymc file is created.\n", "    name.rpym or a compiled module file. If a .rpym file exists, and is newer than the\n    corresponding compiled module file, it is loaded and a new compiled module file is created.\n")

    print(f"Patched SDK copy: {SDK}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"patch_rnx_sdk.py failed: {e}", file=sys.stderr)
        raise
