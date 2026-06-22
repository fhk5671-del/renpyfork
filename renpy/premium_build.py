from __future__ import annotations

import ast
import dataclasses
import fnmatch
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from pickle import HIGHEST_PROTOCOL, dumps
from typing import Any

import renpy.blobstore as blobstore


MANIFEST_NAMES = (
    "game/rnx_premium.json",
    "rnx_premium.json",
    ".rnx/premium_build.json",
    "game/.rnx/premium_build.json",
)

RUNTIME_POLICY_NAME = "game/rnx_premium_policy.json"

DEFAULT_BANNED_TERMS = (
    "sister",
    "brother",
    "cousin",
    "father",
    "mother",
    "daughter",
    "son",
    "uncle",
    "aunt",
)

DEFAULT_BANNED_BOOLEANS = ("rough",)

TIERS = (10, 15)
TIER_SECTIONS = ((0, "non_premium"), (10, "p10"), (15, "p15"))
PACK_CATEGORIES = ("scripts", "images", "voice", "music", "audio", "video", "other")
ASSET_PACK_CATEGORIES = ("images", "voice", "music", "audio", "video", "other")

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".avif", ".bmp", ".gif")
AUDIO_EXTENSIONS = (".ogg", ".opus", ".mp3", ".wav", ".flac", ".m4a")
VIDEO_EXTENSIONS = (".webm", ".mp4", ".mkv", ".avi", ".mov", ".ogv")

TRUE = "true"
FALSE = "false"
UNKNOWN = "unknown"


@dataclasses.dataclass(frozen=True)
class VariableRule:
    name: str
    value: Any = None
    has_value: bool = False

    @classmethod
    def from_value(cls, value: Any) -> "VariableRule":
        if isinstance(value, str):
            return cls(value)

        if isinstance(value, (list, tuple)):
            if not value:
                raise ValueError("variable rules must include a variable name")
            if len(value) == 1:
                return cls(str(value[0]))
            if len(value) == 2:
                return cls(str(value[0]), value[1], True)

        if isinstance(value, dict):
            if "name" not in value:
                raise ValueError("variable rule objects must include a name")
            if "value" in value:
                return cls(str(value["name"]), value["value"], True)
            return cls(str(value["name"]))

        raise ValueError("variable rules must be strings, 2-item arrays, or objects")

    def matches_name(self, name: str) -> bool:
        return name.lower() == self.name.lower()

    def matches_pair(self, name: str, value: Any) -> bool:
        if not self.matches_name(name):
            return False

        if not self.has_value:
            return True

        return self.value == value


class PremiumManifest:
    def __init__(self, path: str, data: dict[str, Any]):
        self.path = path
        self.data = data
        self.game_id = str(data.get("game_id") or data.get("id") or "")

        self.banned_terms = tuple(
            str(i).lower()
            for i in data.get("banned_terms", DEFAULT_BANNED_TERMS)
        )

        self.banned_booleans = tuple(
            str(i).lower()
            for i in data.get("banned_booleans", DEFAULT_BANNED_BOOLEANS)
        )

        self.asset_patterns: dict[int, list[str]] = {}
        self.variable_rules: dict[int, list[VariableRule]] = {}

        for tier, section_name in TIER_SECTIONS:
            section = data.get(section_name, {}) or {}
            self.asset_patterns[tier] = [
                normalize_member_path(i)
                for i in section.get("assets", [])
            ]
            self.variable_rules[tier] = [
                VariableRule.from_value(i)
                for i in section.get("variables", [])
            ]

    def archive_game_id(self, project_name: str) -> str:
        return self.game_id or project_name

    def allowed_archive_names(self, default_names: list[str]) -> list[str]:
        names = self.data.get("allowed_archives", self.data.get("allowed_rnx", None))

        if names is None:
            names = default_names

        rv = []
        for name in names:
            name = os.path.basename(str(name).replace("\\", "/").strip())
            if not name:
                continue
            if "." not in name:
                name += blobstore.ARCHIVE_EXTENSION
            rv.append(name.lower())

        return sorted(set(rv))

    def selected_categories(self, project_data: dict[str, Any]) -> set[str]:
        env_value = os.environ.get("RNX_PREMIUM_CATEGORIES", "").strip()

        if env_value:
            raw = [i.strip() for i in env_value.split(",") if i.strip()]
        else:
            raw = project_data.get("rnx_premium_categories", list(PACK_CATEGORIES))

        rv = {str(i).strip().lower() for i in raw}
        return {i for i in rv if i in PACK_CATEGORIES}

    def asset_floor(self, member_path: str) -> int | None:
        member_path = normalize_member_path(member_path)

        # The lowest explicitly matching tier wins. This lets a specific
        # non_premium asset remain free even if a broader p10 wildcard matches.
        for tier, _section_name in TIER_SECTIONS:
            if any(path_match(member_path, pattern) for pattern in self.asset_patterns[tier]):
                return tier

        return None

    def allows_pair(self, name: str, value: Any) -> bool:
        return any(rule.matches_pair(name, value) for rule in self.variable_rules[0])

    def premium_boolean(self, name: str) -> bool:
        lname = name.lower()

        if lname in self.banned_booleans:
            return True

        if any(term in lname for term in self.banned_terms):
            return True

        for tier in TIERS:
            for rule in self.variable_rules[tier]:
                if rule.matches_name(name):
                    return True

        return False

    def relationship_tainted_name(self, name: str) -> bool:
        lname = name.lower()

        if lname in self.banned_booleans:
            return False

        return any(term in lname for term in self.banned_terms)

    def banned_string_value(self, name: str | None, value: str) -> bool:
        if name is not None and self.allows_pair(name, value):
            return False

        lvalue = value.lower()
        return any(term in lvalue for term in self.banned_terms)


def normalize_member_path(path: str) -> str:
    path = str(path).replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    path = path.lstrip("/")
    if path.startswith("game/"):
        path = path[5:]
    return path


def normalize_project_path(path: str) -> str:
    path = str(path).replace("\\", "/").strip().lstrip("/")
    return path


def path_match(path: str, pattern: str) -> bool:
    path = normalize_member_path(path)
    pattern = normalize_member_path(pattern)

    # Match Ren'Py-like glob semantics: ? and * stay inside one path segment,
    # while ** may cross directories.
    regex = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                regex.append(".*")
                i += 2
            else:
                regex.append("[^/]*")
                i += 1
        elif c == "?":
            regex.append("[^/]")
            i += 1
        else:
            regex.append(re.escape(c))
            i += 1

    return re.match("^" + "".join(regex) + "$", path, re.IGNORECASE) is not None


def find_manifest(project_path: str) -> PremiumManifest | None:
    for rel in MANIFEST_NAMES:
        path = os.path.join(project_path, rel)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PremiumManifest(path, data)

    return None


def project_is_flat(project: Any) -> bool:
    return (
        os.path.normcase(os.path.abspath(project.path)) ==
        os.path.normcase(os.path.abspath(project.gamedir))
    )


def distribution_rel(member_path: str) -> str:
    return "game/" + normalize_member_path(member_path)


def runtime_rel(distribution_path: str) -> str:
    distribution_path = normalize_project_path(distribution_path)
    if distribution_path.startswith("game/"):
        return distribution_path[5:]
    return distribution_path


def project_source_path(project: Any, distribution_path: str) -> str:
    distribution_path = normalize_project_path(distribution_path)

    if distribution_path.startswith("game/"):
        return os.path.join(project.gamedir, distribution_path[5:].replace("/", os.sep))

    return os.path.join(project.path, distribution_path.replace("/", os.sep))


def is_script_source(relpath: str) -> bool:
    lower = relpath.lower()
    return lower.endswith(".rpy") or lower.endswith(".rpym") or lower.endswith("_ren.py")


def compiled_script_path(relpath: str) -> str | None:
    relpath = normalize_project_path(relpath)
    lower = relpath.lower()

    if lower.endswith("_ren.py"):
        return relpath[:-7] + blobstore.COMPILED_SCRIPT_EXTENSION
    if lower.endswith(".rpym"):
        return relpath[:-5] + blobstore.COMPILED_MODULE_EXTENSION
    if lower.endswith(".rpy"):
        return relpath[:-4] + blobstore.COMPILED_SCRIPT_EXTENSION

    return None


def is_compiled_script(relpath: str) -> bool:
    lower = relpath.lower()
    return lower.endswith(blobstore.COMPILED_SCRIPT_EXTENSION) or lower.endswith(blobstore.COMPILED_MODULE_EXTENSION)


def archive_filename(tier: int, category: str = "scripts") -> str:
    if category == "scripts":
        return "p{}{}".format(tier, blobstore.ARCHIVE_EXTENSION)
    return "p{}-{}{}".format(tier, category, blobstore.ARCHIVE_EXTENSION)


def category_for_asset(member_path: str) -> str:
    member_path = normalize_member_path(member_path).lower()
    parts = [i for i in member_path.split("/") if i]
    ext = os.path.splitext(member_path)[1]

    if ext in IMAGE_EXTENSIONS:
        return "images"

    if ext in VIDEO_EXTENSIONS:
        return "video"

    if ext in AUDIO_EXTENSIONS:
        if any(part in ("voice", "voices") for part in parts):
            return "voice"
        if any(part in ("music", "bgm") for part in parts):
            return "music"
        return "audio"

    return "other"


def discover_script_sources(project: Any) -> list[str]:
    rv = []
    skip_dirs = {"saves", "cache", "tmp", "old-game"}

    for root, dirs, files in os.walk(project.gamedir):
        dirs[:] = [d for d in dirs if d.lower() not in skip_dirs]

        for fn in files:
            abs_path = os.path.join(root, fn)
            member_path = normalize_member_path(os.path.relpath(abs_path, project.gamedir))
            rel = distribution_rel(member_path)
            if is_script_source(rel):
                rv.append(rel)

    rv.sort()
    return rv


def discover_game_files(project: Any) -> list[str]:
    rv = []
    skip_dirs = {"saves", "cache", "tmp", "old-game"}

    for root, dirs, files in os.walk(project.gamedir):
        dirs[:] = [d for d in dirs if d.lower() not in skip_dirs]

        for fn in files:
            abs_path = os.path.join(root, fn)
            rel = normalize_member_path(os.path.relpath(abs_path, project.gamedir))
            rv.append(rel)

    rv.sort()
    return rv


def safe_copy_or_link(src: str, dst: str, copy_file: bool) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)

    if copy_file:
        shutil.copy2(src, dst)
        return

    try:
        os.link(src, dst)
    except Exception:
        shutil.copy2(src, dst)


class ConditionSimplifier:
    def __init__(self, manifest: PremiumManifest):
        self.manifest = manifest

    def simplify(self, expression: str) -> tuple[str, str | None]:
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError:
            return UNKNOWN, expression

        return self._node(tree.body, expression)

    def _source(self, node: ast.AST, full_source: str) -> str:
        segment = ast.get_source_segment(full_source, node)
        if segment:
            return segment

        try:
            return ast.unparse(node)
        except Exception:
            return full_source

    def _node(self, node: ast.AST, full_source: str) -> tuple[str, str | None]:
        if isinstance(node, ast.BoolOp):
            return self._boolop(node, full_source)

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            state, expr = self._node(node.operand, full_source)
            if state == TRUE:
                return FALSE, None
            if state == FALSE:
                return TRUE, None
            return UNKNOWN, "not ({})".format(expr or self._source(node.operand, full_source))

        if isinstance(node, ast.Name):
            if self.manifest.premium_boolean(node.id):
                return FALSE, None
            return UNKNOWN, self._source(node, full_source)

        if isinstance(node, ast.Constant):
            if node.value is True:
                return TRUE, None
            if node.value is False:
                return FALSE, None
            return UNKNOWN, self._source(node, full_source)

        if isinstance(node, ast.Compare):
            state = self._compare(node, full_source)
            if state != UNKNOWN:
                return state, None

        return UNKNOWN, self._source(node, full_source)

    def _boolop(self, node: ast.BoolOp, full_source: str) -> tuple[str, str | None]:
        parts: list[str] = []

        if isinstance(node.op, ast.And):
            for value in node.values:
                state, expr = self._node(value, full_source)
                if state == FALSE:
                    return FALSE, None
                if state == UNKNOWN:
                    parts.append(expr or self._source(value, full_source))

            if not parts:
                return TRUE, None
            if len(parts) == 1:
                return UNKNOWN, parts[0]
            return UNKNOWN, " and ".join("({})".format(i) if " or " in i else i for i in parts)

        if isinstance(node.op, ast.Or):
            for value in node.values:
                state, expr = self._node(value, full_source)
                if state == TRUE:
                    return TRUE, None
                if state == UNKNOWN:
                    parts.append(expr or self._source(value, full_source))

            if not parts:
                return FALSE, None
            if len(parts) == 1:
                return UNKNOWN, parts[0]
            return UNKNOWN, " or ".join(parts)

        return UNKNOWN, self._source(node, full_source)

    def _compare(self, node: ast.Compare, full_source: str) -> str:
        if len(node.ops) != 1 or len(node.comparators) != 1:
            return UNKNOWN

        left = node.left
        right = node.comparators[0]
        op = node.ops[0]

        left_name = self._name(left)
        right_name = self._name(right)
        left_value = self._literal(left)
        right_value = self._literal(right)

        if left_name is not None and right_value is not _MISSING:
            return self._compare_name_value(left_name, op, right_value)

        if right_name is not None and left_value is not _MISSING:
            return self._compare_name_value(right_name, op, left_value, reversed_operands=True)

        if left_name is not None and isinstance(op, (ast.In, ast.NotIn)):
            values = self._literal_sequence(right)
            if values is not None:
                return self._compare_name_sequence(left_name, op, values)

        return UNKNOWN

    def _compare_name_value(self, name: str, op: ast.cmpop, value: Any, reversed_operands: bool = False) -> str:
        if self.manifest.premium_boolean(name):
            if isinstance(op, (ast.Eq, ast.Is)):
                return FALSE if value is True else TRUE if value is False else UNKNOWN
            if isinstance(op, (ast.NotEq, ast.IsNot)):
                return TRUE if value is True else FALSE if value is False else UNKNOWN

        if isinstance(value, str) and self.manifest.banned_string_value(name, value):
            if isinstance(op, ast.Eq):
                return FALSE
            if isinstance(op, ast.NotEq):
                return TRUE

            # Reversed containment, like "sister" in relation, is too vague.
            if not reversed_operands:
                if isinstance(op, ast.In):
                    return FALSE
                if isinstance(op, ast.NotIn):
                    return TRUE

        return UNKNOWN

    def _compare_name_sequence(self, name: str, op: ast.cmpop, values: list[Any]) -> str:
        if not values:
            return FALSE if isinstance(op, ast.In) else TRUE

        banned = [
            isinstance(value, str) and self.manifest.banned_string_value(name, value)
            for value in values
        ]

        if all(banned):
            return FALSE if isinstance(op, ast.In) else TRUE

        return UNKNOWN

    def _name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        return None

    def _literal(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id.lower() == "true":
                return True
            if node.id.lower() == "false":
                return False
        return _MISSING

    def _literal_sequence(self, node: ast.AST) -> list[Any] | None:
        if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return None

        rv = []
        for item in node.elts:
            value = self._literal(item)
            if value is _MISSING:
                return None
            rv.append(value)

        return rv


class _Missing:
    pass


_MISSING = _Missing()


IF_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<kind>if|elif)\s+(?P<condition>.+):(?P<trailing>[ \t]*(?:#.*)?)$")
ELSE_RE = re.compile(r"^(?P<indent>[ \t]*)else\s*:(?P<trailing>[ \t]*(?:#.*)?)$")
MENU_CHOICE_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<label>\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*')(?P<rest>.*):(?P<trailing>[ \t]*(?:#.*)?)$")


class ScriptTransformer:
    def __init__(self, manifest: PremiumManifest):
        self.simplifier = ConditionSimplifier(manifest)

    def transform_text(self, text: str) -> str:
        lines = text.splitlines(True)
        transformed = self._transform_range(lines, 0, len(lines))

        if text.endswith("\n") and transformed and not transformed[-1].endswith(("\n", "\r")):
            transformed[-1] += "\n"

        return "".join(transformed)

    def _transform_range(self, lines: list[str], start: int, end: int) -> list[str]:
        out: list[str] = []
        i = start

        while i < end:
            line = lines[i]
            if_match = IF_RE.match(line.rstrip("\r\n"))

            if if_match:
                chain_end, chain_lines = self._transform_if_chain(lines, i, end, len(if_match.group("indent")))
                out.extend(chain_lines)
                i = chain_end
                continue

            menu_choice = self._menu_choice(line)
            if menu_choice is not None:
                block_end = self._block_end(lines, i + 1, end, menu_choice["indent_len"])
                if menu_choice["tainted"]:
                    state, expr = FALSE, None
                else:
                    state, expr = self.simplifier.simplify(menu_choice["condition"])

                if state == FALSE:
                    i = block_end
                    continue

                if state == TRUE:
                    out.append(menu_choice["prefix"] + " if 1 == 1:" + menu_choice["trailing"] + menu_choice["newline"])
                elif expr and expr != menu_choice["condition"]:
                    out.append(menu_choice["prefix"] + " if " + expr + ":" + menu_choice["trailing"] + menu_choice["newline"])
                else:
                    out.append(line)

                out.extend(self._transform_range(lines, i + 1, block_end))
                i = block_end
                continue

            out.append(line)
            i += 1

        return out

    def _transform_if_chain(self, lines: list[str], start: int, end: int, indent_len: int) -> tuple[int, list[str]]:
        branches = []
        i = start

        while i < end:
            raw = lines[i]
            stripped = raw.rstrip("\r\n")
            newline = raw[len(stripped):]
            if_match = IF_RE.match(stripped)
            else_match = ELSE_RE.match(stripped)

            if if_match and len(if_match.group("indent")) == indent_len:
                kind = if_match.group("kind")
                if branches and kind == "if":
                    break
                condition = if_match.group("condition")
                trailing = if_match.group("trailing")
            elif else_match and len(else_match.group("indent")) == indent_len:
                kind = "else"
                condition = None
                trailing = else_match.group("trailing")
            else:
                break

            body_start = i + 1
            body_end = self._block_end(lines, body_start, end, indent_len)
            branches.append((kind, condition, trailing, newline, body_start, body_end))
            i = body_end

            if kind == "else":
                break

        out: list[str] = []
        emitted_any = False

        for kind, condition, trailing, newline, body_start, body_end in branches:
            if condition is None:
                state, expr = TRUE, None
            else:
                state, expr = self.simplifier.simplify(condition)

            if state == FALSE:
                continue

            rendered_body = self._transform_range(lines, body_start, body_end)
            rendered_body = self._ensure_nonempty_body(rendered_body, indent_len + 4)

            if state == TRUE:
                rendered_kind = "if" if not emitted_any else "elif"
                out.append("{}{} 1 == 1:{}{}".format(" " * indent_len, rendered_kind, trailing, newline))
                out.extend(rendered_body)
                emitted_any = True
                break

            rendered_kind = "if" if not emitted_any else kind
            rendered_condition = expr or condition
            out.append("{}{} {}:{}{}".format(" " * indent_len, rendered_kind, rendered_condition, trailing, newline))
            out.extend(rendered_body)
            emitted_any = True

        return i, out

    def _block_end(self, lines: list[str], start: int, end: int, parent_indent: int) -> int:
        i = start

        while i < end:
            line = lines[i]
            if not line.strip():
                i += 1
                continue

            indent = len(line) - len(line.lstrip(" \t"))
            stripped = line.lstrip(" \t")

            if indent <= parent_indent:
                if indent == parent_indent and (stripped.startswith("elif ") or stripped.startswith("else:")):
                    return i
                return i

            i += 1

        return i

    def _ensure_nonempty_body(self, lines: list[str], indent: int) -> list[str]:
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return lines

        return ["{}pass\n".format(" " * indent)]

    def _menu_choice(self, line: str) -> dict[str, Any] | None:
        stripped = line.rstrip("\r\n")
        newline = line[len(stripped):]
        match = MENU_CHOICE_RE.match(stripped)

        if not match:
            return None

        rest = match.group("rest")
        marker = " if "
        if marker not in rest:
            return None

        before, condition = rest.rsplit(marker, 1)
        condition = condition.strip()

        if not condition:
            return None

        prefix = match.group("indent") + match.group("label") + before
        return {
            "indent_len": len(match.group("indent")),
            "condition": condition,
            "tainted": self._condition_has_tainted_name(condition),
            "prefix": prefix,
            "trailing": match.group("trailing"),
            "newline": newline,
            "unconditional": prefix + ":" + match.group("trailing") + newline,
        }

    def _condition_has_tainted_name(self, condition: str) -> bool:
        try:
            tree = ast.parse(condition, mode="eval")
        except SyntaxError:
            return False

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and self.simplifier.manifest.relationship_tainted_name(node.id):
                return True

        return False


class ArchiveWriter:
    def __init__(self, filename: str):
        self.filename = filename
        self.f = open(filename, "wb")
        self.index: dict[str, list[tuple[int, int, int]]] = {}
        self.f.write(blobstore.ARCHIVE_HEADER_PLACEHOLDER)

    def add_bytes(self, name: str, data: bytes) -> None:
        name = normalize_member_path(name)
        sealed = blobstore.seal(data, blobstore.ARCHIVE_MEMBER_PURPOSE)
        offset = self.f.tell()
        self.f.write(sealed)
        self.index[name] = [(offset, len(sealed), len(data))]

    def add_file(self, name: str, path: str) -> None:
        with open(path, "rb") as f:
            self.add_bytes(name, f.read())

    def close(self) -> None:
        index_offset = self.f.tell()
        index = blobstore.seal(dumps(self.index, HIGHEST_PROTOCOL), blobstore.ARCHIVE_INDEX_PURPOSE)
        self.f.write(index)
        self.f.seek(0)
        self.f.write(blobstore.ARCHIVE_HEADER % (index_offset, len(index)))
        self.f.close()


def premium_digest(game_id: str, tier: int, kind: str) -> str:
    text = "rnx-premium-v1|{}|{}|{}".format(kind, game_id, int(tier))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def premium_marker_path(game_id: str, tier: int) -> str:
    return "premium/{}.dat".format(premium_digest(game_id, tier, "path")[:24])


def premium_marker_token(game_id: str, tier: int) -> bytes:
    return ("rnx:" + premium_digest(game_id, tier, "token")).encode("utf-8")


class PremiumBuild:
    def __init__(self, project: Any, project_factory: Any, reporter: Any):
        self.project = project
        self.project_factory = project_factory
        self.reporter = reporter
        self.manifest = find_manifest(project.path)
        self.free_compiled: dict[str, str] = {}
        self.premium_compiled: dict[str, str] = {}
        self.asset_floors: dict[str, int] = {}
        self.script_sources: list[str] = []
        self.categories: set[str] = set(PACK_CATEGORIES)
        self.packs_only = False
        self.enabled = self.manifest is not None

    def prepare(self, packs_only: bool = False) -> "PremiumBuild | None":
        if self.manifest is None:
            return None

        self.packs_only = bool(packs_only)
        self.categories = self.manifest.selected_categories(getattr(self.project, "data", {}))
        self.script_sources = discover_script_sources(self.project)
        self.asset_floors = self._classify_assets()

        self.reporter.info("Preparing RNX premium packs...")

        if not self.packs_only:
            free_dir = self._variant_dir("free")
            self._clone_project(free_dir, transform_scripts=True)
            self._compile_variant(free_dir, "free")
            self.free_compiled = self._collect_compiled(free_dir)

        if "scripts" in self.categories:
            premium_dir = self._variant_dir("premium")
            self._clone_project(premium_dir, transform_scripts=False)
            self._compile_variant(premium_dir, "premium")
            self.premium_compiled = self._collect_compiled(premium_dir)

        if self.packs_only and "scripts" not in self.categories and not any(category in self.categories for category in ASSET_PACK_CATEGORIES):
            raise RuntimeError("No RNX premium pack categories are selected.")

        return self

    def apply_to_file_lists(self, file_lists: dict[str, list[Any]], file_factory: Any, build_archives: list[Any]) -> None:
        if self.manifest is None:
            return

        remove_names = self._base_remove_names()

        for key, entries in list(file_lists.items()):
            file_lists[key] = type(entries)(
                entry for entry in entries
                if normalize_project_path(entry.name) not in remove_names
            )

        for rel, path in sorted(self.free_compiled.items()):
            file_lists["archive"].append(file_factory(rel, path, False, False))

        policy_path = self._write_runtime_policy(build_archives)
        file_lists["all"].append(file_factory(RUNTIME_POLICY_NAME, policy_path, False, False))

    def write_sidecar_packs(self, destination: str) -> list[str]:
        if self.manifest is None:
            return []

        destination = os.path.join(destination, "premium-packs")
        os.makedirs(destination, exist_ok=True)
        game_id = self.manifest.archive_game_id(self.project.name)
        written = []

        for tier in TIERS:
            if "scripts" in self.categories:
                out = os.path.join(destination, archive_filename(tier, "scripts"))
                writer = ArchiveWriter(out)

                writer.add_bytes(premium_marker_path(game_id, tier), premium_marker_token(game_id, tier))

                for rel, path in sorted(self.premium_compiled.items()):
                    writer.add_file(normalize_member_path(runtime_rel(rel)), path)

                writer.close()
                written.append(out)

            for category in ASSET_PACK_CATEGORIES:
                if category not in self.categories:
                    continue

                files = []

                for member_path, floor in sorted(self.asset_floors.items()):
                    if floor <= 0 or floor > tier:
                        continue
                    if category_for_asset(member_path) != category:
                        continue

                    source = os.path.join(self.project.gamedir, member_path.replace("/", os.sep))
                    if os.path.isfile(source):
                        files.append((member_path, source))

                if not files:
                    continue

                out = os.path.join(destination, archive_filename(tier, category))
                writer = ArchiveWriter(out)

                for member_path, source in files:
                    writer.add_file(member_path, source)

                writer.close()
                written.append(out)

        return written

    def _variant_dir(self, name: str) -> str:
        self.project.make_tmp()
        base = os.path.join(self.project.tmp, "rnx_premium_variants")
        path = os.path.join(base, name)

        if os.path.isdir(path):
            shutil.rmtree(path)

        os.makedirs(path, exist_ok=True)
        return path

    def _classify_assets(self) -> dict[str, int]:
        assert self.manifest is not None

        rv = {}
        for member_path in discover_game_files(self.project):
            floor = self.manifest.asset_floor(member_path)
            if floor is not None:
                rv[member_path] = floor

        return rv

    def _clone_project(self, destination: str, transform_scripts: bool) -> None:
        assert self.manifest is not None
        transformer = ScriptTransformer(self.manifest)
        flat = project_is_flat(self.project)

        if flat:
            source_root = self.project.gamedir
            skip_dirs = {
                os.path.normcase(os.path.join(self.project.gamedir, "saves")),
                os.path.normcase(os.path.join(self.project.gamedir, "cache")),
                os.path.normcase(os.path.join(self.project.gamedir, "tmp")),
            }
        else:
            source_root = self.project.path
            skip_dirs = {
                os.path.normcase(os.path.join(self.project.path, "game", "saves")),
                os.path.normcase(os.path.join(self.project.path, "game", "cache")),
                os.path.normcase(os.path.join(self.project.path, "tmp")),
            }

        for root, dirs, files in os.walk(source_root):
            dirs[:] = [
                d for d in dirs
                if os.path.normcase(os.path.join(root, d)) not in skip_dirs
            ]

            for fn in files:
                src = os.path.join(root, fn)
                rel = normalize_project_path(os.path.relpath(src, source_root))
                dist_rel = distribution_rel(rel) if flat else rel

                if rel in MANIFEST_NAMES or dist_rel in MANIFEST_NAMES:
                    continue

                if rel == RUNTIME_POLICY_NAME or dist_rel == RUNTIME_POLICY_NAME:
                    continue

                if rel.lower() in {
                    "game/" + archive_filename(tier, category)
                    for tier in TIERS
                    for category in PACK_CATEGORIES
                } or dist_rel.lower() in {
                    "game/" + archive_filename(tier, category)
                    for tier in TIERS
                    for category in PACK_CATEGORIES
                }:
                    continue

                if is_compiled_script(rel) or is_compiled_script(dist_rel):
                    continue

                dst = os.path.join(destination, rel.replace("/", os.sep))

                if is_script_source(dist_rel):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)

                    if transform_scripts:
                        with open(src, "r", encoding="utf-8-sig") as f:
                            text = f.read()
                        with open(dst, "w", encoding="utf-8", newline="") as f:
                            f.write(transformer.transform_text(text))
                    else:
                        shutil.copy2(src, dst)

                    continue

                safe_copy_or_link(src, dst, copy_file=False)

    def _compile_variant(self, variant_dir: str, label: str) -> None:
        variant_project = self.project_factory(
            variant_dir,
            name="{}-rnx-{}".format(self.project.name, label),
            parent_path=os.path.dirname(variant_dir),
        )
        variant_project.launch(["compile", "--keep-orphan-rsc"], wait=True)

    def _collect_compiled(self, variant_dir: str) -> dict[str, str]:
        rv = {}

        for rel in self.script_sources:
            compiled = compiled_script_path(rel)
            if compiled is None:
                continue

            if project_is_flat(self.project):
                path = os.path.join(variant_dir, runtime_rel(compiled).replace("/", os.sep))
            else:
                path = os.path.join(variant_dir, compiled.replace("/", os.sep))

            if os.path.exists(path):
                rv[compiled] = path
            else:
                raise RuntimeError("Compiled script was not produced: {}".format(compiled))

        return rv

    def _base_remove_names(self) -> set[str]:
        rv = set()

        for rel in self.script_sources:
            rv.add(rel)
            compiled = compiled_script_path(rel)
            if compiled is not None:
                rv.add(compiled)

        for rel in MANIFEST_NAMES:
            rv.add(normalize_project_path(rel))

        rv.add(RUNTIME_POLICY_NAME)

        for tier in TIERS:
            for category in PACK_CATEGORIES:
                rv.add("game/" + archive_filename(tier, category))

        for member_path, floor in self.asset_floors.items():
            if floor > 0:
                rv.add("game/" + member_path)

        return rv

    def _write_runtime_policy(self, build_archives: list[Any]) -> str:
        assert self.manifest is not None

        default_archives = [
            "{}{}".format(archive_name, blobstore.ARCHIVE_EXTENSION)
            for archive_name, _file_lists in build_archives
        ]
        for tier in TIERS:
            for category in PACK_CATEGORIES:
                default_archives.append(archive_filename(tier, category))

        compiled_scripts = sorted(
            normalize_member_path(runtime_rel(rel)).lower()
            for rel in set(self.free_compiled) | set(self.premium_compiled)
        )

        policy = {
            "allowed_archives": self.manifest.allowed_archive_names(default_archives),
            "allowed_compiled_scripts": compiled_scripts,
        }

        path = os.path.join(self.project.tmp, "rnx_premium_policy.json")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(policy, f, indent=2, sort_keys=True)
            f.write("\n")

        return path
