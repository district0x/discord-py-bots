''' namehash()

Author: Noel Maersk (veox)
Version: 0.1.3
License: LGPLv3
'''

# PyPI package 'pycryptodome'
from Crypto.Hash import keccak


def _namehashgen(encoding):
    '''Internal, generator iterator.

    Takes next label (string).

    Yields nodehash (bytes(32)), accounting for label.'''

    # start from nullhash
    nodehash = bytes(32)

    while True:
        label = (yield nodehash)

        # first hash the label...
        lh = keccak.new(data=bytes(label, encoding=encoding))
        labelhash = lh.digest()

        # then hash the result together with the node
        nh = keccak.new(data=nodehash + labelhash)
        nodehash = nh.digest()


def namehashg(name: str, encoding='utf-8'):
    '''ENS "namehash()" convention mapping of strings to bytes(32) hashes.

    Generator-based function variant. Performs worse than the recursive
    variant, but is not limited by the system stack depth limit.

    :param name: name to hash, labels separated by dots
    :type name: str
    :returns: bytes(32)'''

    hg = _namehashgen(encoding)
    h = hg.send(None)

    # short-circuit for empty name
    if name == '':
        return h

    labels = name.split('.')
    for l in reversed(labels):
        h = hg.send(l)
    return h


def namehash(name: str, encoding='utf-8'):
    '''ENS "namehash()" convention mapping of strings to bytes(32) hashes.

    Recursive function variant. Performs slightly better than the
    generator-based variant, but can't handle names with infinite (or
    extremely large) number of labels.

    :param name: name to hash, labels separated by dots
    :type name: str
    :returns: bytes(32)'''

    if name == '':
        return b'\x00' * 32
    else:
        label, _, remainder = name.partition('.')
        return keccak.new(digest_bits=256, data=namehash(remainder) +
                                                keccak.new(data=label.encode(encoding),
                                                           digest_bits=256).digest()).digest()
