import renpy

_VIRTUAL_RPY = r'''
python early hide:

    def _cheat_parse(l):
        code = l.simple_expression()
        if code is None:
            l.error("expected cheat code")

        target = None
        label = None

        if l.match(r","):
            target = l.simple_expression()
            if target is None:
                l.error("expected cheat target")
        elif not l.eol():
            target = l.simple_expression()
            if target is None:
                l.error("expected cheat target")

        if l.match(r","):
            label = l.simple_expression()
            if label is None:
                l.error("expected cheat label")

        if not l.eol():
            l.error("expected end of line")

        return code, target, label

    def _cheat_eval(expr):
        if expr is None:
            return None
        return renpy.python.py_eval(expr)

    def _cheat_exec(parsed):
        code, target, label = parsed
        renpy.store.registercheat(_cheat_eval(code), _cheat_eval(target), label=_cheat_eval(label))

    renpy.statements.register("registercheat", parse=_cheat_parse, execute=_cheat_exec, init=True)

default _cheat_state = {}

init -999 python:

    import hashlib
    import os
    import sys

    import renpy.blobstore as _blobstore

    class _CheatEntry(object):
        def __init__(self, id, code, target, label, action, selected, sensitive, tags):
            self.id = id
            self.code = code
            self.target = target
            self.label = label
            self.action = action
            self.selected = selected
            self.sensitive = sensitive
            self.tags = tuple(tags or ())

    class _CheatRegistry(object):
        def __init__(self):
            self.templates = {}
            self.entries = []
            self.filter = None
            self.menu_title = _("Cheats")
            self.main_menu_label = _("Cheats")

        def find(self, id):
            for entry in self.entries:
                if entry.id == id:
                    return entry
            return None

    _cheat = _CheatRegistry()

    class _PremiumRegistry(object):
        def __init__(self):
            self.tiers = (10, 15)
            self.pack_names = { 10: "p10", 15: "p15" }
            self.game_id = None
            self.cache = None

    _premium = _PremiumRegistry()

    def _cheat_scale(value):
        scale = getattr(gui, "scale", None)
        if scale is not None:
            return scale(value)
        return value

    if not hasattr(gui, "cheat_grid_cols"):
        gui.cheat_grid_cols = 5
    if not hasattr(gui, "cheat_grid_rows"):
        gui.cheat_grid_rows = 6
    if not hasattr(gui, "cheat_button_width"):
        gui.cheat_button_width = _cheat_scale(180)
    if not hasattr(gui, "cheat_button_height"):
        gui.cheat_button_height = _cheat_scale(46)
    if not hasattr(gui, "cheat_button_spacing"):
        gui.cheat_button_spacing = _cheat_scale(10)
    if not hasattr(gui, "cheat_frame_xmaximum"):
        gui.cheat_frame_xmaximum = _cheat_scale(1040)
    if not hasattr(gui, "cheat_frame_ymaximum"):
        gui.cheat_frame_ymaximum = _cheat_scale(560)
    if not hasattr(gui, "cheat_return_button_width"):
        gui.cheat_return_button_width = _cheat_scale(220)
    if not hasattr(gui, "cheat_return_button_height"):
        gui.cheat_return_button_height = _cheat_scale(46)
    if not hasattr(gui, "cheat_main_menu_button_xpos"):
        gui.cheat_main_menu_button_xpos = getattr(gui, "navigation_xpos", _cheat_scale(60))
    if not hasattr(gui, "cheat_main_menu_button_yalign"):
        gui.cheat_main_menu_button_yalign = 0.92
    if not hasattr(gui, "cheat_main_menu_button_width"):
        gui.cheat_main_menu_button_width = getattr(gui, "navigation_button_width", _cheat_scale(250))
    if not hasattr(gui, "cheat_main_menu_button_height"):
        gui.cheat_main_menu_button_height = _cheat_scale(46)

    if not hasattr(config, "cheat_main_menu_entry"):
        config.cheat_main_menu_entry = True

    def _cheat_tags(value):
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        return tuple(value)

    def _cheat_target_name(target):
        if target is None:
            return ""
        text = str(target)
        if not text:
            return text
        return text[:1].upper() + text[1:]

    def define_cheat_template(code, label=None, action=None, selected=None, sensitive=None, tags=()):
        _cheat.templates[str(code)] = dict(label=label, action=action, selected=selected, sensitive=sensitive, tags=_cheat_tags(tags))

    def set_cheat_filter(callback):
        _cheat.filter = callback

    def set_cheat_menu_title(title):
        _cheat.menu_title = title

    def set_cheat_main_menu_label(label):
        _cheat.main_menu_label = label

    def set_premium_game_id(game_id):
        _premium.game_id = str(game_id)
        _premium.cache = None

    def _premium_game_id():
        if _premium.game_id:
            return _premium.game_id

        for value in (
            getattr(config, "save_directory", None),
            getattr(config, "name", None),
            os.path.splitext(os.path.basename(getattr(sys, "renpy_executable", "")))[0],
        ):
            if value:
                return str(value)

        return "game"

    def _premium_digest(kind, tier):
        text = "rnx-premium-v1|{}|{}|{}".format(kind, _premium_game_id(), int(tier))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def premium_marker_path(tier):
        return "premium/{}.dat".format(_premium_digest("path", int(tier))[:24])

    def premium_marker_token(tier):
        return "rnx:" + _premium_digest("token", int(tier))

    def _premium_tier(value):
        if isinstance(value, str):
            key = value.strip().lower().replace("_", " ").replace("-", " ")
            aliases = {
                "p10": 10,
                "10": 10,
                "premium": 10,
                "p15": 15,
                "15": 15,
                "deluxe": 15,
                "premium deluxe": 15,
            }
            if key in aliases:
                return aliases[key]

        return int(value)

    def _premium_archive_bytes(tier, name):
        pack_name = _premium.pack_names.get(int(tier))
        if not pack_name:
            return None

        for archive_name, index in renpy.loader.archives:
            stem = os.path.splitext(os.path.basename(archive_name))[0].lower()
            if stem != pack_name:
                continue
            if name not in index:
                continue

            entry = index[name][0]
            if len(entry) < 2:
                return None

            offset, dlen = entry[0], entry[1]

            try:
                with open(archive_name, "rb") as f:
                    f.seek(offset)
                    data = f.read(dlen)

                return _blobstore.open_sealed(data, _blobstore.ARCHIVE_MEMBER_PURPOSE)
            except Exception:
                return None

        return None

    def _premium_valid(tier):
        marker = premium_marker_path(tier)
        data = _premium_archive_bytes(tier, marker)
        if data is None:
            return False

        try:
            token = data.decode("utf-8").strip()
        except Exception:
            return False

        return token == premium_marker_token(tier)

    def premium_tiers():
        if _premium.cache is None:
            level = 0

            for tier in _premium.tiers:
                if _premium_valid(tier):
                    level = max(level, tier)

            _premium.cache = tuple(tier for tier in _premium.tiers if tier <= level)

        return _premium.cache

    def premium_level():
        tiers = premium_tiers()
        if not tiers:
            return 0
        return max(tiers)

    def premium_at_least(tier):
        return premium_level() >= _premium_tier(tier)

    def premium_has(tier):
        return premium_at_least(tier)

    def registercheat(code, target=None, label=None, action=None, selected=None, sensitive=None, tags=(), id=None, **kwargs):
        code = str(code)
        template = _cheat.templates.get(code, {})
        target_name = _cheat_target_name(target)

        if label is None:
            label = template.get("label")

        if label is None:
            if target is None:
                label = code
            else:
                label = code + " " + target_name
        else:
            label = str(label).format(code=code, target=target_name, name=target_name)

        if action is None:
            action = template.get("action")
        if selected is None:
            selected = template.get("selected")
        if sensitive is None:
            sensitive = template.get("sensitive")

        combined_tags = _cheat_tags(template.get("tags")) + _cheat_tags(tags)

        if id is None:
            id = code + ":" + ("" if target is None else str(target))

        entry = _CheatEntry(str(id), code, target, label, action, selected, sensitive, combined_tags)
        _cheat.entries = [ i for i in _cheat.entries if i.id != entry.id ]
        _cheat.entries.append(entry)
        return entry

    def registercheat_target(key, label=None, **kwargs):
        return registercheat("mhs", key, label=label, **kwargs)

    def unregistercheat(id):
        id = str(id)
        _cheat.entries = [ i for i in _cheat.entries if i.id != id ]

    def cheat_active(code, target=None):
        id = str(code) + ":" + ("" if target is None else str(target))
        return bool(_cheat_state.get(id, False))

    def _cheat_label(entry):
        return entry.label

    def _cheat_selected(entry):
        if entry.selected is None:
            return bool(_cheat_state.get(entry.id, False))
        if callable(entry.selected):
            return bool(entry.selected(entry))
        return bool(entry.selected)

    def _cheat_sensitive(entry):
        if entry.sensitive is None:
            return True
        if callable(entry.sensitive):
            return bool(entry.sensitive(entry))
        return bool(entry.sensitive)

    def _cheat_family(entry):
        words = ("sister", "brother", "cousin", "mother", "father", "daughter", "son", "aunt", "uncle", "niece", "nephew")
        text = (entry.label + " " + str(entry.code) + " " + str(entry.target)).lower()
        return ("fam" in entry.tags) or any(word in text for word in words)

    def _cheat_builtin_filter(entry):
        try:
            if renpy.variant("_ptz") and _cheat_family(entry):
                return False
        except Exception:
            pass
        return True

    def _cheat_allowed(entry):
        if not _cheat_builtin_filter(entry):
            return False
        if _cheat.filter is None:
            return True
        try:
            return bool(_cheat.filter(entry))
        except TypeError:
            return bool(_cheat.filter(entry.id, entry))

    def _cheat_items():
        return [ entry for entry in _cheat.entries if _cheat_allowed(entry) ]

    def _cheat_main_menu_entry_visible():
        if not getattr(config, "cheat_main_menu_entry", True):
            return False
        if not main_menu:
            return False
        try:
            if renpy.get_screen("cheat_menu") is not None:
                return False
        except Exception:
            pass
        return True

    def _cheat_toggle(entry):
        _cheat_state[entry.id] = not _cheat_state.get(entry.id, False)
        renpy.restart_interaction()

    class _CheatAction(Action, DictEquality):
        def __init__(self, id):
            self.id = id

        def __call__(self):
            entry = _cheat.find(self.id)
            if entry is None:
                return
            if entry.action is None:
                return _cheat_toggle(entry)
            return entry.action(entry)

        def get_selected(self):
            entry = _cheat.find(self.id)
            return bool(entry and _cheat_selected(entry))

        def get_sensitive(self):
            entry = _cheat.find(self.id)
            return bool(entry and _cheat_sensitive(entry))

    def _cheat_has_button_art():
        names = ("idle", "hover", "selected_idle", "selected_hover", "insensitive")
        return any(renpy.loadable("gui/button/cheat_" + name + "_background.png") for name in names)

    def _cheat_button_properties():
        if _cheat_has_button_art():
            return gui.button_properties("cheat_button")
        return gui.button_properties("choice_button")

    def _cheat_return_properties():
        return gui.button_properties("navigation_button")

    def _cheat_menu_background():
        if main_menu and hasattr(gui, "main_menu_background"):
            return gui.main_menu_background
        if hasattr(gui, "game_menu_background"):
            return gui.game_menu_background
        return Solid("#0008")

    def _cheat_grid_ymaximum(items):
        rows = max(1, min(gui.cheat_grid_rows, (len(items) + gui.cheat_grid_cols - 1) // gui.cheat_grid_cols))
        return rows * gui.cheat_button_height + max(0, rows - 1) * gui.cheat_button_spacing

    define_cheat_template("mhs", "Make {name} the protagonist's sister", tags=("fam", "rel"))
    define_cheat_template("mhd", "Make {name} the protagonist's daughter", tags=("fam", "rel"))
    define_cheat_template("mhc", "Make {name} the protagonist's cousin", tags=("fam", "rel"))
    define_cheat_template("mhn", "Make {name} the protagonist's niece", tags=("fam", "rel"))
    define_cheat_template("mhgd", "Make {name} the protagonist's girlfriend's daughter", tags=("fam", "rel"))
    define_cheat_template("ps", "Make the protagonist more pushy")

    if "_cheat_main_menu_entry" not in config.overlay_screens:
        config.overlay_screens.append("_cheat_main_menu_entry")

screen _cheat_main_menu_entry():
    zorder 90

    if _cheat_main_menu_entry_visible():
        vbox:
            style "cheat_main_menu_vbox"

            textbutton _cheat.main_menu_label:
                style "cheat_main_menu_button"
                action ShowMenu("cheat_menu")

screen cheat_menu(title=None):
    tag menu

    $ items = _cheat_items()
    $ menu_title = title or _cheat.menu_title

    add _cheat_menu_background()

    frame:
        style "cheat_outer_frame"

        has vbox:
            style "cheat_vbox"

        if menu_title:
            text menu_title style "cheat_title"

        if items:
            vpgrid:
                style "cheat_grid"
                cols gui.cheat_grid_cols
                ymaximum _cheat_grid_ymaximum(items)
                scrollbars "vertical"
                mousewheel True
                draggable True
                pagekeys True

                for entry in items:
                    textbutton _cheat_label(entry):
                        style "cheat_button"
                        selected _cheat_selected(entry)
                        sensitive _cheat_sensitive(entry)
                        action _CheatAction(entry.id)
        else:
            null height gui.cheat_button_height

        textbutton _("Return"):
            style "cheat_return_button"
            action Return()

    key "game_menu" action Return()

style cheat_outer_frame is empty:
    xfill True
    yfill True
    background "#0008"

style cheat_vbox is vbox:
    xalign 0.5
    yalign 0.5
    xmaximum gui.cheat_frame_xmaximum
    ymaximum gui.cheat_frame_ymaximum
    spacing _cheat_scale(18)

style cheat_title is text:
    xalign 0.5
    textalign 0.5
    size _cheat_scale(34)

style cheat_grid is vpgrid:
    xalign 0.5
    spacing gui.cheat_button_spacing

style cheat_button is button:
    properties _cheat_button_properties()
    xsize gui.cheat_button_width
    ysize gui.cheat_button_height

style cheat_button_text is button_text:
    properties gui.text_properties("choice_button")
    xalign 0.5
    textalign 0.5

style cheat_return_button is button:
    properties _cheat_return_properties()
    xalign 0.5
    xsize gui.cheat_return_button_width
    ysize gui.cheat_return_button_height

style cheat_return_button_text is button_text:
    properties gui.text_properties("button")
    xalign 0.5
    textalign 0.5

style cheat_main_menu_vbox is vbox:
    xpos gui.cheat_main_menu_button_xpos
    yalign gui.cheat_main_menu_button_yalign

style cheat_main_menu_button is button:
    properties _cheat_return_properties()
    xsize gui.cheat_main_menu_button_width
    ysize gui.cheat_main_menu_button_height

style cheat_main_menu_button_text is button_text:
    properties gui.text_properties("button")
    xalign 0.5
    textalign 0.5
'''

def _patch_script_loader():
    import renpy.script

    script_class = renpy.script.Script
    if getattr(script_class, "_host_cheat_installed", False):
        return

    old_sort = script_class.sort_script_files
    old_load = script_class.load_appropriate_file

    def sort_script_files(self):
        rv = old_sort(self)
        if rv:
            marker = (0, "__host_cheat", "__host__") if len(rv[0]) == 3 else ("__host_cheat", "__host__")
        else:
            marker = ("__host_cheat", "__host__")

        if marker not in rv:
            rv.insert(0, marker)
        return rv

    def load_appropriate_file(self, compiled, source_extensions, dir, fn, initcode):
        if dir == "__host__" and fn == "__host_cheat":
            _stmts, extra = self.load_string("__host_cheat.rpy", _VIRTUAL_RPY)
            if extra:
                initcode.extend(extra)
            return
        return old_load(self, compiled, source_extensions, dir, fn, initcode)

    script_class.sort_script_files = sort_script_files
    script_class.load_appropriate_file = load_appropriate_file
    script_class._host_cheat_installed = True

def _install():
    if hasattr(renpy, "script"):
        _patch_script_loader()
        return

    old_import_all = renpy.import_all

    def import_all():
        rv = old_import_all()
        _patch_script_loader()
        return rv

    renpy.import_all = import_all

_install()
