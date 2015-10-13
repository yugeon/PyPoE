"""
Path     PyPoE/poe/file/idl.py
Name     .idl File Format
Version  1.0.0a0
Revision $Id$
Author   [#OMEGA]- K2

INFO

File Format handler for Grinding Gear Games' .idl format.

.idl files are used to link multiple virtual texture out of single image file.


AGREEMENT

See PyPoE/LICENSE


TODO

...
"""

# =============================================================================
# Imports
# =============================================================================

# Python
import codecs
import re

# self
from PyPoE.poe.file._shared import AbstractFile
from PyPoE.shared.containers import Record, TypedList, TypedContainerMeta

# =============================================================================
# Globals
# =============================================================================

__all__ = ['IDLRecord', 'IDLFile']

# =============================================================================
# Classes
# =============================================================================

class IDLRecord(Record):
    __slots__ = ['destination', 'source', 'x1', 'y1', 'x2', 'y2']

    def __init__(self, destination, source, x1, y1, x2, y2):
        """
        Creates a new IDLRecord instance.

        The coordinates (x1, y1) and (x2, y2) can be understood as the upper
        left and lower right corner of a bounding rectangle respectively.

        :param str destination: destination file (virtual path)
        :param str source: source image file (internal path)
        :param int x1: Upper left x coordinate
        :param int y1: Upper left y coordinate
        :param int x2: Lower right x coordinate
        :param int y2: Lower right y coordinate
        """
        self.destination = destination
        self.source = source
        self.x1 = int(x1)
        self.y1 = int(y1)
        self.x2 = int(x2)
        self.y2 = int(y2)

    def __str__(self):
        return '"%s" "%s" %i %i %i %i' % (
            self.destination,
            self.source,
            self.x1,
            self.y1,
            self.x2,
            self.y2,
        )


class IDLFile(AbstractFile, TypedList, metaclass=TypedContainerMeta):
    """
    Encapsulated in-memory representation of .idl files.

    Since .idl files basically act as list of :class:`IDLRecord`s IDLFile also
    acts as a list, i.e. it supports the regular list interface.
    However, added items may only be a :class:`IDLRecord`
    """

    ACCEPTED_TYPES = IDLRecord

    _regex_parse = re.compile(
        r'^'
        r'"(?P<destination>[\w\./_]+)"[ ]+'
        r'"(?P<source>[\w\./_]+)"[ ]+'
        r'(?P<x1>[0-9]+)[ ]+'
        r'(?P<y1>[0-9]+)[ ]+'
        r'(?P<x2>[0-9]+)[ ]+'
        r'(?P<y2>[0-9]+)[ ]*'
        r'$',
        re.UNICODE | re.MULTILINE
    )

    def __init__(self):
        AbstractFile.__init__(self)
        TypedList.__init__(self)

    def _read(self, buffer, *args, **kwargs):
        # Reset
        TypedList.__init__(self)

        data = buffer.read().decode('utf-16')

        for match in self._regex_parse.finditer(data):
            self.append(IDLRecord(**match.groupdict()))

    def _write(self, buffer, *args, **kwargs):
        lines = []
        for record in self:
            lines.append(str(record))
            lines.append('\n')

        buffer.write(codecs.BOM_UTF16_LE + ''.join(lines).encode('utf-16_le'))