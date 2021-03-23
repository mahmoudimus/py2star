from Crypto.Util.py3compat import bord
from Crypto.Util._raw_api import (
    load_pycryptodome_raw_lib,
    VoidPointer,
    SmartPointer,
    create_string_buffer,
    get_raw_buffer,
    c_size_t,
    c_uint8_ptr,
)

_raw_sha256_lib = load_pycryptodome_raw_lib(
    "Crypto.Hash._SHA256",
    "\n                        int SHA256_init(void **shaState);\n                        int SHA256_destroy(void *shaState);\n                        int SHA256_update(void *hs,\n                                          const uint8_t *buf,\n                                          size_t len);\n                        int SHA256_digest(const void *shaState,\n                                          uint8_t *digest,\n                                          size_t digest_size);\n                        int SHA256_copy(const void *src, void *dst);\n\n                        int SHA256_pbkdf2_hmac_assist(const void *inner,\n                                            const void *outer,\n                                            const uint8_t *first_digest,\n                                            uint8_t *final_digest,\n                                            size_t iterations,\n                                            size_t digest_size);\n                        ",
)
"A SHA-256 hash object.\n    Do not instantiate directly. Use the :func:`new` function.\n\n    :ivar oid: ASN.1 Object ID\n    :vartype oid: string\n\n    :ivar block_size: the size in bytes of the internal message block,\n                      input to the compression function\n    :vartype block_size: integer\n\n    :ivar digest_size: the size in bytes of the resulting hash\n    :vartype digest_size: integer\n    "
digest_size = 32
block_size = 64
oid = "2.16.840.1.101.3.4.2.1"


def __init__(self, data=None):
    state = VoidPointer()
    result = _raw_sha256_lib.SHA256_init(state.address_of())
    if result:
        raise ValueError(("Error %d while instantiating SHA256" % result))
    self._state = SmartPointer(state.get(), _raw_sha256_lib.SHA256_destroy)
    if data:
        self.update(data)


def update(self, data):
    "Continue hashing of a message by consuming the next chunk of data.\n\n        Args:\n            data (byte string/byte array/memoryview): The next chunk of the message being hashed.\n        "
    result = _raw_sha256_lib.SHA256_update(
        self._state.get(), c_uint8_ptr(data), c_size_t(len(data))
    )
    if result:
        raise ValueError(("Error %d while hashing data with SHA256" % result))


def digest(self):
    "Return the **binary** (non-printable) digest of the message that has been hashed so far.\n\n        :return: The hash digest, computed over the data processed so far.\n                 Binary form.\n        :rtype: byte string\n        "
    bfr = create_string_buffer(self.digest_size)
    result = _raw_sha256_lib.SHA256_digest(
        self._state.get(), bfr, c_size_t(self.digest_size)
    )
    if result:
        raise ValueError(("Error %d while making SHA256 digest" % result))
    return get_raw_buffer(bfr)


def hexdigest(self):
    "Return the **printable** digest of the message that has been hashed so far.\n\n        :return: The hash digest, computed over the data processed so far.\n                 Hexadecimal encoded.\n        :rtype: string\n        "
    return "".join([("%02x" % bord(x)) for x in self.digest()])


def copy(self):
    'Return a copy ("clone") of the hash object.\n\n        The copy will have the same internal state as the original hash\n        object.\n        This can be used to efficiently compute the digests of strings that\n        share a common initial substring.\n\n        :return: A hash object of the same type\n        '
    clone = SHA256Hash()
    result = _raw_sha256_lib.SHA256_copy(self._state.get(), clone._state.get())
    if result:
        raise ValueError(("Error %d while copying SHA256" % result))
    return clone


def new(self, data=None):
    "Create a fresh SHA-256 hash object."
    return SHA256Hash(data)


def new(data=None):
    "Create a new hash object.\n\n    :parameter data:\n        Optional. The very first chunk of the message to hash.\n        It is equivalent to an early call to :meth:`SHA256Hash.update`.\n    :type data: byte string/byte array/memoryview\n\n    :Return: A :class:`SHA256Hash` hash object\n    "
    return SHA256Hash().new(data)


digest_size = SHA256Hash.digest_size
block_size = SHA256Hash.block_size


def _pbkdf2_hmac_assist(inner, outer, first_digest, iterations):
    "Compute the expensive inner loop in PBKDF-HMAC."
    assert iterations > 0
    bfr = create_string_buffer(len(first_digest))
    result = _raw_sha256_lib.SHA256_pbkdf2_hmac_assist(
        inner._state.get(),
        outer._state.get(),
        first_digest,
        bfr,
        c_size_t(iterations),
        c_size_t(len(first_digest)),
    )
    if result:
        raise ValueError(("Error %d with PBKDF2-HMAC assist for SHA256" % result))
    return get_raw_buffer(bfr)
