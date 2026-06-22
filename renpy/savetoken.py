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
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode  # *

import base64
import hashlib
import os
import zipfile
import zlib

import renpy

try:
    import renpy.ecsign as _ecsign
except ImportError:
    _ecsign = None
    import ecdsa as _ecdsa  # type: ignore


# The directory containing the save token information.
token_dir = None  # type: str|None

# A list of the keys used to sign saves, stored as DER-encoded bytes.
signing_keys = []  # type: list[bytes]

# A list of the keys used to verify saves, stored as DER-encoded bytes.
verifying_keys = []  # type: list[bytes]

# True if the save files and persistent data should be upgraded.
should_upgrade = False  # type: bool

# Save and persistent payloads are sealed before being written to disk. The key
# is still embedded in the client, so this is not DRM against a determined local
# reverse engineer. It does stop casual zip/pickle editing and rejects tampered
# payloads before unpickling.
PROTECTED_DATA_MAGIC = b"RENPY-SAVE-SEAL-1\0"
LOCAL_DATA_MAGIC = b"RENPY-LOCAL-SEAL-1\0"
_SAVE_SEAL_SECRET = b"renpy-fork-rnx-save-seal-2026-06-22"


def encode_line(key, a, b=None):  # type (str, bytes, bytes|None) -> str
    """
    This encodes a line that contains a key and up to 2 base64-encoded fields.
    It returns the line with the newline appended, as a string.
    """

    if b is None:
        return key + " " + base64.b64encode(a).decode("ascii") + "\n"
    else:
        return key + " " + base64.b64encode(a).decode("ascii") + " " + base64.b64encode(b).decode("ascii") + "\n"


def decode_line(line):  # type (str) -> (str, bytes, bytes|None)
    """
    This decodes a line that contains a key and up to 2 base64-encoded fields.
    It returns a tuple of the key, the first field, and the second field.
    If the second field is not present, it is None.
    """

    line = line.strip()

    if not line or line[0] == "#":
        return "", b"", None

    parts = line.split(None, 2)

    try:
        if len(parts) == 2:
            return parts[0], base64.b64decode(parts[1]), None
        else:
            return parts[0], base64.b64decode(parts[1]), base64.b64decode(parts[2])
    except Exception:
        return "", b"", None


def _purpose_bytes(purpose):
    if isinstance(purpose, bytes):
        return purpose

    return purpose.encode("utf-8")


def _save_token_game_id():
    save_directory = renpy.config.save_directory or ""

    if save_directory:
        return save_directory

    gamedir = renpy.config.gamedir or ""

    try:
        return os.path.abspath(gamedir)
    except Exception:
        return gamedir


def _save_directory_bytes():
    return _save_token_game_id().encode("utf-8", "surrogateescape")


def _derive_seal_key(public_key, purpose):
    h = hashlib.sha256()
    h.update(_SAVE_SEAL_SECRET)
    h.update(b"\0signed\0")
    h.update(_purpose_bytes(purpose))
    h.update(b"\0")
    h.update(_save_directory_bytes())
    h.update(b"\0")
    h.update(public_key)
    return h.digest()


def _derive_local_seal_key(purpose):
    h = hashlib.sha256()
    h.update(_SAVE_SEAL_SECRET)
    h.update(b"\0local\0")
    h.update(_purpose_bytes(purpose))
    return h.digest()


def _current_public_key():
    if not signing_keys:
        raise ValueError("Save payload sealing requires a save token signing key.")

    public = _get_public_key_from_private(signing_keys[0])

    if public is None:
        raise ValueError("Save payload sealing could not derive a public key.")

    return public


def _generate_private_key():
    if _ecsign is not None:
        return _ecsign.generate_private_key()

    return _ecdsa.SigningKey.generate(curve=_ecdsa.NIST256p).to_der()


def _get_public_key_from_private(private_key):
    if _ecsign is not None:
        return _ecsign.get_public_key_from_private(private_key)

    sk = _ecdsa.SigningKey.from_der(private_key)

    if sk is not None and sk.verifying_key is not None:
        return sk.verifying_key.to_der()

    return None


def _sign_data(data, private_key):
    if _ecsign is not None:
        return _ecsign.sign_data(data, private_key)

    return _ecdsa.SigningKey.from_der(private_key).sign(data)


def _verify_data(data, public_key, sig):
    if _ecsign is not None:
        return _ecsign.verify_data(data, public_key, sig)

    try:
        return _ecdsa.VerifyingKey.from_der(public_key).verify(sig, data)
    except Exception:
        return False


def _validate_private_key(private_key):
    if _ecsign is not None:
        return _ecsign.validate_private_key(private_key)

    try:
        _ecdsa.SigningKey.from_der(private_key)
        return True
    except Exception:
        return False


def _validate_public_key(public_key):
    if _ecsign is not None:
        return _ecsign.validate_public_key(public_key)

    try:
        _ecdsa.VerifyingKey.from_der(public_key)
        return True
    except Exception:
        return False


def is_protected_data(data):
    """
    Returns True if `data` is a sealed save/persistent payload.
    """

    return isinstance(data, bytes) and data.startswith(PROTECTED_DATA_MAGIC)


def protect_data(data, purpose):
    """
    Compresses and seals signed save/persistent payload data.
    """

    if is_protected_data(data):
        return data

    public = _current_public_key()
    compressed = zlib.compress(data, 3)
    sealed = renpy.encryption.secretbox_encrypt(compressed, _derive_seal_key(public, purpose))
    return PROTECTED_DATA_MAGIC + sealed


def unprotect_data(data, signatures, purpose):
    """
    Opens a sealed save/persistent payload after its signature has been checked.
    """

    if not is_protected_data(data):
        raise ValueError("Save payload is not sealed.")

    body = data[len(PROTECTED_DATA_MAGIC) :]
    keys = get_keys_from_signatures(signatures)

    for key in keys:
        try:
            compressed = renpy.encryption.secretbox_decrypt(body, _derive_seal_key(key, purpose))
            return zlib.decompress(compressed)
        except Exception:
            pass

    raise ValueError("Save payload could not be opened.")


def protect_local_data(data, purpose):
    """
    Seals local shared data that does not have a per-file signature.
    """

    if isinstance(data, bytes) and data.startswith(LOCAL_DATA_MAGIC):
        return data

    compressed = zlib.compress(data, 3)
    sealed = renpy.encryption.secretbox_encrypt(compressed, _derive_local_seal_key(purpose))
    return LOCAL_DATA_MAGIC + sealed


def unprotect_local_data(data, purpose):
    if not (isinstance(data, bytes) and data.startswith(LOCAL_DATA_MAGIC)):
        raise ValueError("Local persistent payload is not sealed.")

    body = data[len(LOCAL_DATA_MAGIC) :]
    compressed = renpy.encryption.secretbox_decrypt(body, _derive_local_seal_key(purpose))
    return zlib.decompress(compressed)


def sign_data(data):
    """
    Signs `data` with the signing keys and returns the
    signature. If there are no signing keys, returns None.
    """

    rv = ""

    for i in signing_keys:
        sig = _sign_data(data, i)
        public = _get_public_key_from_private(i)
        rv += encode_line("signature", public, sig)

    return rv


def verify_data(data, signatures, check_verifying=True):
    """
    Verifies that `data` has been signed by the keys in `signatures`.
    """

    for i in signatures.splitlines():
        kind, key, sig = decode_line(i)

        if kind == "signature":
            if key is None or sig is None:
                continue

            if check_verifying and key not in verifying_keys:
                continue

            return _verify_data(data, key, sig)

    return False


def get_keys_from_signatures(signatures):
    """
    Given a string containing signatures, get the verification keys
    for those signatures.
    """

    rv = []

    for l in signatures.splitlines():
        kind, key, _ = decode_line(l)

        if kind == "signature":
            rv.append(key)

    return rv


def check_load(log, signatures):
    """
    This checks the token that was loaded from a save file to see if it's
    valid. If not, it will prompt the user to confirm the load.
    """

    if not is_protected_data(log):
        return False

    if verify_data(log, signatures):
        return True

    def ask(prompt):
        """
        Asks the user a yes/no question. Returns True if the user says yes,
        and false otherwise.
        """

        return renpy.exports.invoke_in_new_context(renpy.store.layout.yesno_prompt, None, prompt)

    if not ask(renpy.store.gui.UNKNOWN_TOKEN):
        return False

    new_keys = [i for i in get_keys_from_signatures(signatures) if i not in verifying_keys]

    if new_keys and token_dir is not None and ask(renpy.store.gui.TRUST_TOKEN):
        keys_text = os.path.join(token_dir, "security_keys.txt")

        with open(keys_text, "a") as f:
            for k in new_keys:
                f.write(encode_line("verifying-key", k))
                verifying_keys.append(k)

    if not signatures:
        return False

    # This check catches the case where the signature is not correct.
    return verify_data(log, signatures, False)


def check_persistent(data, signatures):
    """
    This checks a persistent file to see if the token is valid.
    """

    if not is_protected_data(data):
        return False

    if verify_data(data, signatures):
        return True

    return False


def create_token(filename):
    """
    Creates a token and writes it to `filename`, if possible.
    """

    try:
        os.makedirs(os.path.dirname(filename))
    except Exception:
        pass

    sk = _generate_private_key()
    if sk is None:
        raise Exception("Failed to generate signing key")
    vk = _get_public_key_from_private(sk)
    if vk is not None:
        line = encode_line("signing-key", sk, vk)

        with open(filename, "a") as f:
            f.write(line)


def upgrade_savefile(fn):
    """
    Given a savegame, fn, upgrades it to include the token.
    """

    if signing_keys is None:
        return

    atime = os.path.getatime(fn)
    mtime = os.path.getmtime(fn)

    with zipfile.ZipFile(fn, "a") as zf:
        if "signatures" in zf.namelist():
            return

        log = zf.read("log")

        if not is_protected_data(log):
            return

        zf.writestr("signatures", sign_data(log))

    os.utime(fn, (atime, mtime))


def upgrade_all_savefiles():
    if token_dir is None:
        return

    if not should_upgrade:
        return

    upgraded_txt = os.path.join(token_dir, "upgraded.txt")

    for fn in renpy.loadsave.location.list_files():
        try:
            upgrade_savefile(fn)
        except:
            renpy.display.log.write("Error upgrading save file:")
            renpy.display.log.exception()

    upgraded = True

    with open(upgraded_txt, "a") as f:
        f.write(_save_token_game_id() + "\n")


def load_tokens(keys_fn):
    """
    Loads the tokens from the file `keys_fn`, which is expected to be in the
    format produced by `create_token`.
    """

    global signing_keys
    global verifying_keys

    signing_keys = []
    verifying_keys = []

    # Load the signing and verifying keys.
    with open(keys_fn, "r") as f:
        for l in f:
            kind, key, _ = decode_line(l)

            if kind == "signing-key":
                public = _get_public_key_from_private(key)
                if public is not None:
                    signing_keys.append(key)
                    verifying_keys.append(public)
            elif kind == "verifying-key":
                verifying_keys.append(key)


def init_tokens():
    global token_dir
    global signing_keys
    global verifying_keys
    global should_upgrade

    # Determine the current save token, and the list of accepted save tokens.
    token_dir = renpy.__main__.path_to_saves(renpy.config.gamedir, "tokens")

    if token_dir is None:
        return

    keys_fn = os.path.join(token_dir, "security_keys.txt")

    if os.path.exists(keys_fn):
        load_tokens(keys_fn)

    if not signing_keys:
        # If there are no signing keys, we create a new token.
        create_token(keys_fn)
        load_tokens(keys_fn)

    # Process config.save_token_keys

    for tk in renpy.config.save_token_keys:
        k = base64.b64decode(tk)
        if _validate_public_key(k):
            verifying_keys.append(k)
        else:
            if _validate_private_key(k):
                public = _get_public_key_from_private(k)
                if public is not None:
                    vk = base64.b64encode(public).decode("utf-8")
                else:
                    vk = ""

                raise Exception(
                    "In config.save_token_keys, the signing key {!r} was provided, but the verifying key {!r} is required.".format(
                        tk, vk
                    )
                )
            else:
                raise Exception("In config.save_token_keys, the key {!r} is not a valid key.".format(tk))

    # Determine if we need to upgrade the current game.

    upgraded_txt = os.path.join(token_dir, "upgraded.txt")

    if os.path.exists(upgraded_txt):
        with open(upgraded_txt, "r") as f:
            upgraded_games = f.read().splitlines()
    else:
        upgraded_games = []

    if _save_token_game_id() in upgraded_games:
        return

    should_upgrade = True


def init():
    try:
        init_tokens()
    except Exception:
        renpy.display.log.write("Initializing save token:")
        renpy.display.log.exception()

        import traceback

        traceback.print_exc()


def get_save_token_keys():
    """
    :undocumented:

    Returns the list of save token keys.
    """

    rv = []

    for i in signing_keys:
        public = _get_public_key_from_private(i)

        if public is not None:
            rv.append(base64.b64encode(public).decode("utf-8"))

    return rv
