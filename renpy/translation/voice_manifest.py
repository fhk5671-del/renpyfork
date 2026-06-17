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

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals

import ast
import csv
import hashlib
import itertools
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import renpy


SAY_RE = re.compile(
    r"^(?:(?P<speaker>[A-Za-z_][A-Za-z0-9_]*)\s+)?(?P<string>(?:r|u|ur|ru)?\".*\")(?P<tail>\s+with\s+.+)?$",
    re.I,
)
LABEL_RE = re.compile(r"^label\s+([A-Za-z_][A-Za-z0-9_.]*)\s*:")
IF_RE = re.compile(r"^(if|elif)\s+(.+):$")
ELSE_RE = re.compile(r"^else\s*:")
SUB_RE = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*)(?:!([A-Za-z]))?\]")
DEFAULT_TAG_PATTERN = r"/([A-Za-z][A-Za-z0-9 _'-]{0,60})/"

DEFAULT_SKIP_SPEAKERS = {
    "add",
    "bar",
    "default",
    "define",
    "frame",
    "hbox",
    "image",
    "input",
    "key",
    "label",
    "play",
    "scene",
    "show",
    "text",
    "textbutton",
    "use",
    "voice",
    "vbox",
    "window",
}


@dataclass
class Condition:
    expr: str
    indent: int


@dataclass
class SourceLine:
    source_key: str
    file: str
    line_number: int
    label: str
    speaker: str
    text_template: str
    conditions: list[str] = field(default_factory=list)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def pop_for_indent(stack: list[Condition], indent: int, last_by_indent: dict[int, str]) -> None:
    while stack and stack[-1].indent >= indent:
        popped = stack.pop()
        last_by_indent[popped.indent] = popped.expr


def invert_expr(expr: str) -> str:
    if expr.startswith("not "):
        return expr[4:].strip()
    return "not (%s)" % expr


def parse_string_literal(token: str) -> str | None:
    try:
        value = ast.literal_eval(token)
    except Exception:
        return None

    if not isinstance(value, str):
        return None

    return value


def extract_say(stripped: str, skip_speakers: set[str]) -> tuple[str, str] | None:
    if not stripped or stripped.startswith("#"):
        return None

    if stripped.startswith(("if ", "elif ", "else", "label ", "menu", "$", "python:", "init ")):
        return None

    if stripped.endswith(":") and stripped.startswith('"'):
        return None

    match = SAY_RE.match(stripped)
    if not match:
        return None

    speaker = match.group("speaker") or "narrator"
    if speaker in skip_speakers:
        return None

    text = parse_string_literal(match.group("string"))
    if text is None:
        return None

    return speaker, text


def default_source_key(rel_path: str, line_number: int) -> str:
    rel_path = rel_path.replace("\\", "/")
    if rel_path.startswith("game/"):
        rel_path = rel_path[5:]
    return "%s:%s" % (rel_path, line_number)


def source_key_for(rel_path: str, line_number: int) -> str:
    callback = getattr(renpy.config, "voice_manifest_source_key_callback", None)
    if callable(callback):
        value = callback(rel_path, line_number)
        if value:
            return str(value)

    return default_source_key(rel_path, line_number)


def parse_script_file(path: Path, rel_path: str, skip_speakers: set[str]) -> list[SourceLine]:
    rows: list[SourceLine] = []
    current_label = "start"
    condition_stack: list[Condition] = []
    last_by_indent: dict[int, str] = {}

    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.rstrip("\n")
            stripped = line.strip()

            if not stripped:
                continue

            indent = indent_of(line)
            pop_for_indent(condition_stack, indent, last_by_indent)

            label_match = LABEL_RE.match(stripped)
            if label_match:
                current_label = label_match.group(1)
                continue

            if ELSE_RE.match(stripped):
                previous = last_by_indent.get(indent)
                if previous:
                    condition_stack.append(Condition(invert_expr(previous), indent))
                continue

            if_match = IF_RE.match(stripped)
            if if_match:
                kind, expr = if_match.groups()
                expr = expr.strip()

                if kind == "elif":
                    previous = last_by_indent.get(indent)
                    if previous:
                        expr = "(%s) and (%s)" % (invert_expr(previous), expr)

                condition_stack.append(Condition(expr, indent))
                continue

            say = extract_say(stripped, skip_speakers)
            if say is None:
                continue

            speaker, text = say
            rows.append(
                SourceLine(
                    source_key=source_key_for(rel_path, line_number),
                    file=rel_path.replace("\\", "/"),
                    line_number=line_number,
                    label=current_label,
                    speaker=speaker,
                    text_template=text,
                    conditions=[condition.expr for condition in condition_stack],
                )
            )

    return rows


def combine_profiles(config: dict[str, Any]) -> list[dict[str, Any]]:
    profiles_config = config.get("profiles", None)
    if profiles_config:
        profiles = []
        for profile_name, profile_data in profiles_config.items():
            profiles.append(
                {
                    "profile": profile_name,
                    "dimensions": dict(profile_data.get("dimensions", {})),
                    "state": dict(profile_data.get("state", {})),
                    "variables": dict(profile_data.get("variables", {})),
                }
            )
        return profiles

    dimensions = config.get("dimensions", {}) or {}
    if not dimensions:
        return [
            {
                "profile": config.get("default_profile") or "default",
                "dimensions": {},
                "state": {},
                "variables": {},
            }
        ]

    dimension_items = []
    for dimension_name, dimension in dimensions.items():
        dimension_items.append((dimension_name, list(dimension["profiles"].items())))

    profiles = []
    for combo in itertools.product(*[items for _, items in dimension_items]):
        profile_parts = []
        state: dict[str, Any] = {}
        variables: dict[str, str] = {}
        dimensions_used: dict[str, str] = {}

        for (dimension_name, _items), (profile_name, profile_data) in zip(dimension_items, combo):
            profile_parts.append(profile_name)
            dimensions_used[dimension_name] = profile_name
            state.update(profile_data.get("state", {}))
            variables.update(profile_data.get("variables", {}))

        profiles.append(
            {
                "profile": "__".join(profile_parts),
                "dimensions": dimensions_used,
                "state": state,
                "variables": variables,
            }
        )

    return profiles


def eval_simple_condition(expr: str, state: dict[str, Any]) -> bool | None:
    expr = expr.strip()

    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError:
        return None

    def eval_node(item: ast.AST) -> bool | str | int | None:
        if isinstance(item, ast.BoolOp):
            values = [eval_node(v) for v in item.values]
            if any(v is None for v in values):
                return None
            if isinstance(item.op, ast.And):
                return all(bool(v) for v in values)
            if isinstance(item.op, ast.Or):
                return any(bool(v) for v in values)
            return None

        if isinstance(item, ast.UnaryOp) and isinstance(item.op, ast.Not):
            value = eval_node(item.operand)
            return None if value is None else not bool(value)

        if isinstance(item, ast.Name):
            return state.get(item.id, None)

        if isinstance(item, ast.Constant):
            return item.value

        if isinstance(item, ast.Compare) and len(item.ops) == 1 and len(item.comparators) == 1:
            left = eval_node(item.left)
            right = eval_node(item.comparators[0])
            if left is None or right is None:
                return None

            op = item.ops[0]
            if isinstance(op, ast.Eq):
                return left == right
            if isinstance(op, ast.NotEq):
                return left != right
            if isinstance(op, ast.Is):
                return left is right
            if isinstance(op, ast.IsNot):
                return left is not right

        return None

    result = eval_node(node)
    return None if result is None else bool(result)


def profile_allows(profile: dict[str, Any], conditions: list[str]) -> tuple[bool, list[str]]:
    unresolved = []

    for condition in conditions:
        result = eval_simple_condition(condition, profile["state"])
        if result is False:
            return False, unresolved
        if result is None:
            unresolved.append(condition)

    return True, unresolved


def apply_case(value: str, flag: str | None) -> str:
    if flag == "c":
        return value[:1].upper() + value[1:]
    if flag == "u":
        return value.upper()
    return value


def render_text(template: str, variables: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        flag = match.group(2)

        if name not in variables:
            missing.append(name)
            return match.group(0)

        return apply_case(str(variables[name]), flag)

    return SUB_RE.sub(replace, template), sorted(set(missing))


def normalize_voice_tag_spaces(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def compile_tag_re(pattern: str | re.Pattern[str] | None) -> re.Pattern[str]:
    if pattern is None:
        pattern = DEFAULT_TAG_PATTERN
    if hasattr(pattern, "sub"):
        return pattern  # type: ignore
    return re.compile(str(pattern))


def transform_tag(tag: str, config: dict[str, Any], kind: str) -> str:
    tag = normalize_voice_tag_spaces(tag)

    callback_name = "voice_manifest_%s_tag_callback" % kind
    callback = getattr(renpy.config, callback_name, None)
    if callable(callback):
        value = callback(tag)
        return "" if value is None else str(value)

    format_key = "%s_tag_format" % kind
    if format_key in config:
        return str(config[format_key]).format(tag=tag)

    if kind == "tts":
        return "[%s] " % tag

    return ""


def strip_voice_tags(text: str, config: dict[str, Any]) -> str:
    tag_re = compile_tag_re(config.get("tag_pattern", None))
    return normalize_voice_tag_spaces(tag_re.sub(lambda m: transform_tag(m.group(1), config, "display"), text))


def voice_tags_to_tts(text: str, config: dict[str, Any]) -> str:
    tag_re = compile_tag_re(config.get("tag_pattern", None))
    return normalize_voice_tag_spaces(tag_re.sub(lambda m: transform_tag(m.group(1), config, "tts"), text))


def content_hash(label: str, speaker: str, text: str) -> str:
    digest = hashlib.sha1(("%s\n%s\n%s" % (label, speaker, text)).encode("utf-8")).hexdigest()
    return digest[:8]


def safe_slug(value: str, max_len: int = 28) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return (slug[:max_len].strip("_") or "line")


def make_voice_id(row: dict[str, Any], duplicate_index: int) -> str:
    callback = getattr(renpy.config, "voice_manifest_voice_id_callback", None)
    if callable(callback):
        value = callback(row, duplicate_index)
        if value:
            return str(value)

    hash_callback = getattr(renpy.config, "voice_manifest_hash_callback", None)
    if callable(hash_callback):
        digest = str(hash_callback(row["label"], row["speaker"], row["tts_text"], row))
    else:
        digest = content_hash(row["label"], row["speaker"], row["tts_text"])

    base_id = "%s_%s_%s" % (safe_slug(row["label"]), safe_slug(row["speaker"], 8), digest)
    return base_id if duplicate_index == 1 else "%s_%s" % (base_id, duplicate_index)


def read_dialogue_tab(path: Path) -> dict[tuple[str, int], str]:
    if not path.exists():
        return {}

    result: dict[tuple[str, int], str] = {}

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            filename = (row.get("Filename") or "").replace("\\", "/")
            line_raw = row.get("Line Number") or ""
            identifier = row.get("Identifier") or ""

            if not filename or not line_raw or not identifier:
                continue

            if filename.startswith("game/"):
                filename = filename[5:]

            try:
                line_number = int(line_raw)
            except ValueError:
                continue

            result[(filename, line_number)] = identifier

    return result


def resolve_runtime_audio_path(repo_root: Path, audio_path: str) -> Path:
    normalized = audio_path.replace("\\", "/")
    if normalized.startswith("game/"):
        return repo_root / normalized
    if normalized.startswith("audio/"):
        return repo_root / "game" / normalized
    return repo_root / normalized


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    column: "|".join(str(v) for v in row[column])
                    if isinstance(row.get(column), list)
                    else str(row.get(column, ""))
                    for column in columns
                }
            )


def path_relative_to(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return None


def default_script_relpath(path: Path) -> str:
    gamedir = Path(renpy.config.gamedir or (Path(renpy.config.basedir) / "game"))
    basedir = Path(renpy.config.basedir)

    rel = path_relative_to(path, gamedir)
    if rel:
        return rel

    rel = path_relative_to(path, basedir)
    if rel:
        if rel.startswith("game/"):
            return rel[5:]
        return rel

    return path.name


def resolve_script_file(value: str) -> tuple[Path, str]:
    basedir = Path(renpy.config.basedir)
    gamedir = Path(renpy.config.gamedir or (basedir / "game"))
    raw = Path(value)

    if raw.is_absolute():
        path = raw
        rel = default_script_relpath(path)
        return path, rel

    value_posix = value.replace("\\", "/")
    candidates = [
        basedir / value,
        gamedir / value,
    ]

    if not value_posix.startswith("game/"):
        candidates.append(basedir / "game" / value)

    for candidate in candidates:
        if candidate.exists():
            rel = value_posix[5:] if value_posix.startswith("game/") else value_posix
            return candidate, rel

    return candidates[0], value_posix[5:] if value_posix.startswith("game/") else value_posix


def discover_script_files() -> list[tuple[Path, str]]:
    result: list[tuple[Path, str]] = []
    commondir = Path(os.path.normpath(renpy.config.commondir)) if renpy.config.commondir else None
    gamedir = Path(renpy.config.gamedir or (Path(renpy.config.basedir) / "game"))
    tl_dir = gamedir / renpy.config.tl_directory

    for dirname, filename in renpy.loader.listdirfiles():
        if dirname is None:
            continue

        path = Path(dirname) / filename
        if path.suffix not in (".rpy", ".rpym"):
            continue

        if commondir and path_relative_to(path, commondir) is not None:
            continue

        if path_relative_to(path, tl_dir) is not None:
            continue

        result.append((path, default_script_relpath(path)))

    return result


def get_setting(config_data: dict[str, Any], key: str, config_name: str, default: Any) -> Any:
    if key in config_data:
        return config_data[key]

    value = getattr(renpy.config, config_name, None)
    if value is not None:
        return value

    return default


def load_export_config(config_path: str | None) -> dict[str, Any]:
    config_data: dict[str, Any] = {}

    if config_path:
        path = Path(config_path)
        if not path.is_absolute():
            path = Path(renpy.config.basedir) / path
        config_data.update(load_json(path))
    else:
        default_path = getattr(renpy.config, "voice_manifest_config", None)
        if default_path:
            path = Path(default_path)
            if not path.is_absolute():
                path = Path(renpy.config.basedir) / path
            if path.exists():
                config_data.update(load_json(path))

    config_data["script_files"] = get_setting(
        config_data, "script_files", "voice_manifest_script_files", config_data.get("script_files", None)
    )
    config_data["profiles"] = get_setting(config_data, "profiles", "voice_manifest_profiles", config_data.get("profiles", None))
    config_data["dimensions"] = get_setting(
        config_data, "dimensions", "voice_manifest_dimensions", config_data.get("dimensions", None)
    )
    config_data["default_profile"] = get_setting(
        config_data, "default_profile", "voice_manifest_default_profile", config_data.get("default_profile", "default")
    )
    config_data["include_narration"] = bool(
        get_setting(config_data, "include_narration", "voice_manifest_include_narration", True)
    )
    config_data["audio_pattern"] = get_setting(
        config_data, "audio_pattern", "voice_manifest_audio_pattern", "voice/{voice_id}.ogg"
    )
    config_data["speaker_names"] = get_setting(config_data, "speaker_names", "voice_manifest_speaker_names", {})
    config_data["skip_speakers"] = get_setting(
        config_data, "skip_speakers", "voice_manifest_skip_speakers", sorted(DEFAULT_SKIP_SPEAKERS)
    )
    config_data["tag_pattern"] = get_setting(config_data, "tag_pattern", "voice_manifest_tag_pattern", DEFAULT_TAG_PATTERN)
    config_data["tts_tag_format"] = get_setting(config_data, "tts_tag_format", "voice_manifest_tts_tag_format", "[{tag}] ")
    config_data["display_tag_format"] = get_setting(
        config_data, "display_tag_format", "voice_manifest_display_tag_format", ""
    )

    return config_data


def format_audio_path(pattern: str, row: dict[str, Any]) -> str:
    callback = getattr(renpy.config, "voice_manifest_export_audio_path_callback", None)
    if callable(callback):
        value = callback(row)
        if value:
            return str(value)

    return pattern.format(**row)


def audit_audio(repo_root: Path, out_dir: Path, rows: list[dict[str, Any]], audio_lines_dir: str) -> dict[str, Any]:
    expected_by_path = {resolve_runtime_audio_path(repo_root, row["audio_path"]).resolve(): row for row in rows}
    expected_voice_ids = {row["voice_id"] for row in rows}

    missing = []
    for path, row in expected_by_path.items():
        if path.exists():
            continue

        missing.append(
            {
                "status": "missing",
                "voice_id": row["voice_id"],
                "recording_group": row["recording_group"],
                "speaker": row["speaker"],
                "speaker_name": row["speaker_name"],
                "rendered_text": row["rendered_text"],
                "profiles": row["profiles"],
                "source_key": row["source_key"],
                "expected_audio_path": str(path),
                "found_audio_path": "",
                "size": "",
                "last_write": "",
            }
        )

    stale = []
    audio_root = repo_root / audio_lines_dir
    audio_extensions = {".mp3", ".ogg", ".wav", ".flac", ".m4a", ".opus"}

    if audio_root.exists():
        for path in audio_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in audio_extensions:
                continue

            resolved = path.resolve()
            if resolved in expected_by_path:
                continue

            voice_id = path.stem
            stale.append(
                {
                    "status": "stale",
                    "voice_id": voice_id,
                    "recording_group": "",
                    "speaker": "",
                    "speaker_name": "",
                    "rendered_text": "",
                    "profiles": "",
                    "source_key": "",
                    "expected_audio_path": "",
                    "found_audio_path": str(path),
                    "size": path.stat().st_size,
                    "last_write": path.stat().st_mtime,
                    "known_voice_id_with_different_path": voice_id in expected_voice_ids,
                }
            )

    missing.sort(key=lambda row: (row["recording_group"], row["source_key"], row["voice_id"]))
    stale.sort(key=lambda row: row["found_audio_path"])
    audit_rows = missing + stale
    columns = [
        "status",
        "voice_id",
        "recording_group",
        "speaker",
        "speaker_name",
        "rendered_text",
        "profiles",
        "source_key",
        "expected_audio_path",
        "found_audio_path",
        "size",
        "last_write",
        "known_voice_id_with_different_path",
    ]

    write_csv(out_dir / "voice_audio_audit.csv", audit_rows, columns)
    write_json(
        out_dir / "voice_audio_audit.json",
        {
            "missing_count": len(missing),
            "stale_count": len(stale),
            "audio_lines_dir": str(audio_root),
            "missing": missing,
            "stale": stale,
        },
    )

    markdown = [
        "# Voice Audio Audit",
        "",
        "- Missing current voice files: %s" % len(missing),
        "- Stale voice files: %s" % len(stale),
        "- Canonical audio folder: `%s`" % audio_root,
        "",
        "Stale files are not deleted by this audit.",
        "",
    ]

    if missing:
        markdown.extend(["## First Missing", ""])
        for row in missing[:50]:
            markdown.append("- `%s` %s: %s" % (row["voice_id"], row["speaker"], row["rendered_text"]))
        markdown.append("")

    if stale:
        markdown.extend(["## First Stale", ""])
        for row in stale[:50]:
            markdown.append("- `%s` `%s`" % (row["voice_id"], row["found_audio_path"]))
        markdown.append("")

    (out_dir / "voice_audio_audit.md").write_text("\n".join(markdown), encoding="utf-8")

    return {
        "missing_count": len(missing),
        "stale_count": len(stale),
        "audio_lines_dir": str(audio_root),
    }


def build_voice_manifest(
    config_data: dict[str, Any],
    dialogue_ids: dict[tuple[str, int], str] | None = None,
) -> tuple[list[dict[str, Any]], list[SourceLine], dict[str, Any]]:
    dialogue_ids = dialogue_ids or {}
    profiles = combine_profiles(config_data)
    profiles_by_name = {profile["profile"]: profile for profile in profiles}
    default_profile = config_data.get("default_profile") or (profiles[0]["profile"] if profiles else "default")

    if default_profile not in profiles_by_name:
        raise SystemExit("default_profile %r is not generated by the configured profiles." % default_profile)

    script_files = config_data.get("script_files")
    if script_files:
        script_paths = [resolve_script_file(rel_path) for rel_path in script_files]
    else:
        script_paths = discover_script_files()

    skip_speakers = set(config_data.get("skip_speakers") or [])
    source_lines: list[SourceLine] = []

    for path, rel_path in script_paths:
        source_lines.extend(parse_script_file(path, rel_path, skip_speakers))

    if not config_data.get("include_narration", True):
        source_lines = [source for source in source_lines if source.speaker != "narrator"]

    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    default_by_source: dict[str, str] = {}
    source_order = {line.source_key: index for index, line in enumerate(source_lines)}

    for source in source_lines:
        rendered_by_profile: dict[str, dict[str, Any]] = {}

        for profile in profiles:
            allowed, unresolved_conditions = profile_allows(profile, source.conditions)
            if not allowed:
                continue

            rendered, missing = render_text(source.text_template, profile["variables"])
            display_text = strip_voice_tags(rendered, config_data)
            tts_text = voice_tags_to_tts(rendered, config_data)

            rendered_by_profile[profile["profile"]] = {
                "rendered": display_text,
                "tts_text": tts_text,
                "missing": missing,
                "unresolved_conditions": unresolved_conditions,
            }

        if default_profile in rendered_by_profile:
            default_by_source[source.source_key] = rendered_by_profile[default_profile]["rendered"]

        for profile_name, rendered_info in rendered_by_profile.items():
            key = (source.source_key, rendered_info["rendered"], rendered_info["tts_text"])
            if key not in rows_by_key:
                renpy_id = dialogue_ids.get((source.file, source.line_number), "")
                rows_by_key[key] = {
                    "source_key": source.source_key,
                    "file": source.file,
                    "line_number": source.line_number,
                    "label": source.label,
                    "speaker": source.speaker,
                    "speaker_name": config_data.get("speaker_names", {}).get(source.speaker, source.speaker),
                    "text_template": source.text_template,
                    "rendered_text": rendered_info["rendered"],
                    "tts_text": rendered_info["tts_text"],
                    "conditions": source.conditions,
                    "unresolved_conditions": set(rendered_info["unresolved_conditions"]),
                    "missing_variables": set(rendered_info["missing"]),
                    "profiles": set(),
                    "renpy_id": renpy_id,
                }

            row = rows_by_key[key]
            row["profiles"].add(profile_name)
            row["unresolved_conditions"].update(rendered_info["unresolved_conditions"])
            row["missing_variables"].update(rendered_info["missing"])

    grouped_by_voice_base: dict[tuple[str, str, str], int] = {}
    rows = list(rows_by_key.values())
    rows.sort(key=lambda row: (source_order[row["source_key"]], row["rendered_text"]))

    for row in rows:
        base_key = (row["label"], row["speaker"], row["tts_text"])
        grouped_by_voice_base[base_key] = grouped_by_voice_base.get(base_key, 0) + 1
        duplicate_index = grouped_by_voice_base[base_key]

        row["profiles"] = sorted(row["profiles"])
        row["is_default"] = default_profile in row["profiles"]
        row["default_rendered_text"] = default_by_source.get(row["source_key"], "")
        row["recording_group"] = "default_dialogue" if row["is_default"] else "variant_patch"
        row["variant_of_voice_id"] = ""
        row["unresolved_conditions"] = sorted(row["unresolved_conditions"])
        row["missing_variables"] = sorted(row["missing_variables"])
        row["voice_id"] = make_voice_id(row, duplicate_index)
        row["audio_path"] = format_audio_path(config_data["audio_pattern"], row)

    default_voice_by_source: dict[str, str] = {row["source_key"]: row["voice_id"] for row in rows if row["is_default"]}

    for row in rows:
        if not row["is_default"]:
            row["variant_of_voice_id"] = default_voice_by_source.get(row["source_key"], "")

    lookup = {
        "format": 1,
        "default_profile": default_profile,
        "audio_pattern": config_data["audio_pattern"],
        "profiles": [profile["profile"] for profile in profiles],
        "by_source_key": {},
        "by_renpy_id": {},
    }

    for row in rows:
        source_entry = lookup["by_source_key"].setdefault(row["source_key"], {})
        for profile_name in row["profiles"]:
            source_entry[profile_name] = row["voice_id"]

        if row["renpy_id"]:
            renpy_entry = lookup["by_renpy_id"].setdefault(row["renpy_id"], {})
            for profile_name in row["profiles"]:
                renpy_entry[profile_name] = row["voice_id"]

    return rows, source_lines, lookup


def write_manifest_outputs(
    out_dir: Path,
    rows: list[dict[str, Any]],
    source_lines: list[SourceLine],
    lookup: dict[str, Any],
    default_profile: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_columns = [
        "voice_id",
        "recording_group",
        "is_default",
        "variant_of_voice_id",
        "speaker",
        "speaker_name",
        "rendered_text",
        "tts_text",
        "text_template",
        "profiles",
        "default_rendered_text",
        "label",
        "file",
        "line_number",
        "source_key",
        "renpy_id",
        "audio_path",
        "conditions",
        "unresolved_conditions",
        "missing_variables",
    ]

    write_csv(out_dir / "voice_lines.csv", rows, csv_columns)
    write_json(out_dir / "voice_lines.json", rows)

    default_lines = []
    for row in rows:
        if row["is_default"]:
            default_lines.append(
                {
                    "id": row["voice_id"],
                    "speaker": row["speaker_name"],
                    "text": row["rendered_text"],
                    "tts_text": row["tts_text"],
                    "source_key": row["source_key"],
                    "label": row["label"],
                    "renpy_id": row["renpy_id"],
                }
            )

    variant_lines = []
    rows_by_source_order = {row["source_key"]: row for row in rows if row["is_default"]}
    source_keys_in_order = [line.source_key for line in source_lines]

    for row in rows:
        if row["is_default"]:
            continue

        source_index = source_keys_in_order.index(row["source_key"]) if row["source_key"] in source_keys_in_order else -1
        previous_text = ""
        next_text = ""

        if source_index > 0:
            previous_default = rows_by_source_order.get(source_keys_in_order[source_index - 1])
            previous_text = previous_default["rendered_text"] if previous_default else ""

        if 0 <= source_index < len(source_keys_in_order) - 1:
            next_default = rows_by_source_order.get(source_keys_in_order[source_index + 1])
            next_text = next_default["rendered_text"] if next_default else ""

        variant_lines.append(
            {
                "id": row["voice_id"],
                "speaker": row["speaker_name"],
                "text": row["rendered_text"],
                "tts_text": row["tts_text"],
                "previous_text": previous_text,
                "next_text": next_text,
                "source_key": row["source_key"],
                "label": row["label"],
                "profiles": row["profiles"],
                "variant_of": row["variant_of_voice_id"],
                "renpy_id": row["renpy_id"],
            }
        )

    write_json(
        out_dir / "voice_default_dialogue.json",
        {
            "comment": "Default-profile lines for external voice generation.",
            "default_profile": default_profile,
            "lines": default_lines,
        },
    )
    write_json(
        out_dir / "voice_variant_patches.json",
        {
            "comment": "Non-default rendered lines. Generate individually or in small context patches.",
            "default_profile": default_profile,
            "lines": variant_lines,
        },
    )
    write_json(out_dir / "voice_lookup.json", lookup)


def voice_manifest_command():
    """
    Exports a profile-aware voice-line manifest and runtime lookup.
    """

    ap = renpy.arguments.ArgumentParser(description="Exports a profile-aware voice-line manifest.")
    ap.add_argument("--config", default=None, help="JSON config file. Defaults to config.voice_manifest_config.")
    ap.add_argument("--out-dir", default=None, help="Output directory. Defaults to voice_manifest in the base directory.")
    ap.add_argument(
        "--runtime-lookup",
        default=None,
        help="Path to also write the runtime lookup. Use an empty string to disable.",
    )
    ap.add_argument("--dialogue-tab", default="", help="Optional dialogue.tab to merge by file/line.")
    ap.add_argument("--audit-audio", action="store_true", help="Report missing and stale canonical voice files.")
    ap.add_argument("--audio-lines-dir", default=None, help="Folder to scan when --audit-audio is used.")
    args = ap.parse_args()

    repo_root = Path(renpy.config.basedir)
    config_data = load_export_config(args.config)
    default_profile = config_data.get("default_profile") or "default"

    dialogue_ids = read_dialogue_tab(Path(args.dialogue_tab)) if args.dialogue_tab else {}
    rows, source_lines, lookup = build_voice_manifest(config_data, dialogue_ids)

    out_dir = Path(args.out_dir) if args.out_dir else repo_root / "voice_manifest"
    if not out_dir.is_absolute():
        out_dir = repo_root / out_dir

    write_manifest_outputs(out_dir, rows, source_lines, lookup, default_profile)

    runtime_lookup = args.runtime_lookup
    if runtime_lookup is None:
        runtime_lookup = getattr(renpy.config, "voice_manifest_runtime_lookup", "game/audio/voice/manifest/voice_lookup.json")

    if runtime_lookup:
        runtime_path = Path(runtime_lookup)
        if not runtime_path.is_absolute():
            runtime_path = repo_root / runtime_path
        write_json(runtime_path, lookup)

    if args.audit_audio:
        audio_lines_dir = args.audio_lines_dir or getattr(
            renpy.config, "voice_manifest_audio_lines_dir", "game/audio/voice/lines"
        )
        audit = audit_audio(repo_root, out_dir, rows, audio_lines_dir)
        print("missing current voice files: %s" % audit["missing_count"])
        print("stale voice files: %s" % audit["stale_count"])
        print("wrote %s" % (out_dir / "voice_audio_audit.csv"))

    print("source lines: %s" % len(source_lines))
    print("voice rows: %s" % len(rows))
    print("default dialogue rows: %s" % len([row for row in rows if row["is_default"]]))
    print("variant patch rows: %s" % len([row for row in rows if not row["is_default"]]))
    print("wrote %s" % (out_dir / "voice_lines.csv"))

    if runtime_lookup:
        print("wrote %s" % runtime_path)

    return False


renpy.arguments.register_command("voice_manifest", voice_manifest_command)
