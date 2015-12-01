"""
Dat Reader Tool

Overview
-------------------------------------------------------------------------------

+----------+------------------------------------------------------------------+
| Path     | PyPoE/poe/file/dat.py                                            |
+----------+------------------------------------------------------------------+
| Version  | 1.0.0a0                                                          |
+----------+------------------------------------------------------------------+
| Revision | $Id$                                                             |
+----------+------------------------------------------------------------------+
| Author   | Omega_K2                                                         |
+----------+------------------------------------------------------------------+

Description
-------------------------------------------------------------------------------

Toolkit for reading & writing GGG .dat files.

.dat files can be found in Data/ and are read by the class DatFile.
Unfortunately, there is no magic keyword for identifying the GGG .dat format,
so advise caution when trying to read dat files.

The GGG .dat format uses a fixed-width table and a variable-length data section.
In the fixed-width table, the number of rows is defined, however, the data
format stored has to be reverse-engineered and is currently not stored in the
file itself.
The data is a continuous amount of binary data; reading values form there is
generally done by pointers (int) or list pointers (size, int) from the
table-data.

A list of default specification is included with PyPoE; to reload those or load
other specifications, load_spec may be used.

Agreement
-------------------------------------------------------------------------------

See PyPoE/LICENSE

TODO
-------------------------------------------------------------------------------

- DatValue.get_value might hit the python recursion limit, but is not a problem
  for any of the actual dat file.
"""

# =============================================================================
# Imports
# =============================================================================

# Python
import struct
from io import BytesIO
from collections import OrderedDict

# 3rd Party Library
import configobj
import validate

# Library imports
from PyPoE import DAT_SPECIFICATION, DAT_SPECIFICATION_CONFIGSPEC
from PyPoE.shared.decorators import deprecated, doc
from PyPoE.shared.mixins import ReprMixin
from PyPoE.poe.file.shared import AbstractFileReadOnly
from PyPoE.poe.file.shared.cache import AbstractFileCache

# =============================================================================
# Globals
# =============================================================================

_default_spec = None


__all__ = [
    'SpecificationError',
    'DatFile', 'RelationalReader',
    'load_spec', 'reload_default_spec',
]

# =============================================================================
# Classes
# =============================================================================


class SpecificationError(ValueError):
    pass


class DatValue(object):
    """
    Representation of a value found in a dat file.

    DatValue instances are created by reading or writing a DatValue and should
    not be directly be created. The purpose of DatValues is to keep information
    regarding the placement of the value in the respective DatFile intact.


    Support for built-ins:

    DatValue do support comparison, however is it performed on the dereferenced
    value it holds, not the equality of the dat value itself.

    This means generally DatValues can be compared to anything, the actual
    comparison is however performed depending on the data type.
    Example 1: dat_value < 0
    - works if the dat_value holds an integer
    - raises TypeError if it holds a list
    Example 2: dat_value1 < dat_value2
    - works if both dat values have the same or comparable types
    - raises TypeError if one holds a list, and the other an integer


    Dev notes:
    Must keep the init
    """

    # Very important to cut down the cost of class creation
    # In some dat files we may be creating millions of instances, simply using
    # slots can make a significant difference (~35% speedup)
    __slots__ = [
        'value', 'size', 'offset', 'parent', 'specification', 'children',
        'child',
    ]

    def __init__(self, value=None, offset=None, size=None, parent=None, specification=None):
        self.value = value
        self.size = size
        self.offset = offset
        self.parent = parent
        self.specification = specification
        self.children = None
        self.child = None

    def __repr__(self):
        #TODO: iterative vs recursive?
        if self.is_pointer:
            return repr(self.child)
        elif self.is_list:
            return repr([repr(dv) for dv in self.children])
        else:
            return 'DatValue(' + repr(self.value) +')'

    def __lt__(self, other):
        if not isinstance(other, DatValue):
            return self.get_value() < other

        return self.get_value() < other.get_value()

    def __le__(self, other):
        if not isinstance(other, DatValue):
            return self.get_value() <= other

        return self.get_value() <= other.get_value()

    def __eq__(self, other):
        if not isinstance(other, DatValue):
            return self.get_value() == other

        return self.get_value() == other.get_value()

    def __ne__(self, other):
        if not isinstance(other, DatValue):
            return self.get_value() != other

        return self.get_value() != other.get_value()

    def __gt__(self, other):
        if not isinstance(other, DatValue):
            return self.get_value() > other

        return self.get_value() > other.get_value()

    def __ge__(self, other):
        if not isinstance(other, DatValue):
            return self.get_value() >= other

        return self.get_value() >= other.get_value()
    # Properties

    def _get_data_size(self):
        """
        Retrieves site of the data held by the current instance in the data
        section.

        :raises TypeError: If performed on DatValue instances without data

        :return: Returns the end offset
        """
        if self.is_list:
            if self.children:
                size = self.children[0].size * self.value[0]
            else:
                size = 0
        elif self.is_pointer:
            size = self.child.size
        else:
            raise TypeError('Only supported on DatValue instances with data (lists, pointers)')
        return size

    def _get_data_start_offset(self):
        """
        Retrieves the start offset of the data held by the current instance in
        the data section.

        :raises TypeError: If performed on DatValue instances without data

        :return: Returns the start offset
        """
        if self.is_list:
            return self.value[1]
        elif self.is_pointer:
            return self.value
        else:
            raise TypeError('Only supported on DatValue instances with data (lists, pointers)')

    def _get_data_end_offset(self):
        """
        Retrieves the end offset of the data held by the current instance in the
        data section.

        :raises TypeError: If performed on DatValue instances without data

        :return: Returns the end offset
        """
        return self._get_data_start_offset() + self._get_data_size()

    def _is_data(self):
        """
        Whether this DatValue instance is data or not.

        :return: True or False
        :rtype: bool
        """
        return self.parent is not None

    def _has_data(self):
        """
        Whether this DatValue instance has data or not; this applies to types
        that hold a pointer.

        :return: True or False
        :rtype: bool
        """
        return self.is_list or self.is_pointer

    def _is_list(self):
        """
        Whether this DatValue instance is a list.

        :return: True or False
        :rtype: bool
        """
        return self.children is not None

    def _is_pointer(self):
        """
        Whether this DatValue instance is a pointer.

        :return: True or False
        :rtype: bool
        """
        return self.child is not None

    def _is_parsed(self):
        """
        Whether this DatValue instance is parsed (i.e. non bytes).

        :return: True or False
        :rtype: bool
        """
        return not isinstance(self.value, bytes)

    data_size = property(fget=_get_data_size)
    data_start_offset = property(fget=_get_data_start_offset)
    data_end_offset = property(fget=_get_data_end_offset)
    is_data = property(fget=_is_data)
    has_data = property(fget=_has_data)
    is_list = property(fget=_is_list)
    is_pointer = property(fget=_is_pointer)
    is_parsed = property(fget=_is_parsed)

    # Public

    def get_value(self):
        """
        Returns the value that is held by the DatValue instance. This is done
        recursively, i.e. pointers will be dereferenced accordingly.

        This means if you want the actual value of the DatValue, you should
        probably access the value attribute instead.


        If this DatValue instance is a list, this means a python list of items
        will be returned.
        If this DatValue instance is a pointer, this means whatever value the
        child of this instance holds will be returned.
        Otherwise the value of the DatValue instance itself will be returned.

        Note, that values may be nested i.e. if a list contains a list, a
        nested list will be returned accordingly.

        :return: Returns the dereference value
        """
        if self.is_pointer:
            return self.child.get_value()
        elif self.is_list:
            return [dv.get_value() for dv in self.children]
        else:
            return self.value


class RecordList(list):
    """
    :ivar DatReader parent:
    :ivar int rowid:
    """

    __slots__ = ['parent', 'rowid']

    def __init__(self, parent, rowid):
        """
        :param DatReader parent:
        :param int rowid:
        """
        list.__init__(self)
        self.parent = parent
        self.rowid = rowid

    def __getitem__(self, item):
        if isinstance(item, str):
            if item in self.parent.table_columns:
                value = list.__getitem__(self, self.parent.table_columns[item]['index'])
                if isinstance(value, DatValue):
                    value = value.get_value()
                return value
            elif item in self.parent.specification['virtual_fields']:
                field = self.parent.specification['virtual_fields'][item]
                value = [self[fn] for fn in field['fields']]
                if field['zip']:
                    value = zip(*value)
                return value
            else:
                raise KeyError(item)
        return list.__getitem__(self, item)

    def __repr__(self):
        stuff = ["{%s: %s}" % (k, self[i]) for i, k in enumerate(self.parent.table_columns)]
        return '[%s]' % ', '.join(stuff)
    '''def find_all(self, key, value):
        row_index = self._get_column_index(key)
        values = []
        for row in self:
            if row[row_index] == value:
                values.append(value)
        return values'''

    def iter(self):
        """
        Iterates over the RecordList and returns key, value and index
        """
        for index, key in enumerate(self.parent.table_columns):
            yield key, self[key], index


    def keys(self):
        return self.parent.table_columns.keys()


class DatReader(ReprMixin):
    """
    :cvar int _table_offset: Starting offset of table data in bytes
    :cvar _cast_table: Mapping of cast type to the corresponding struct
    type and the size of the cast in bytes
    :type _cast_table: dict[str, list[str, int]]
    :cvar bytes _data_magic_number: Magic number that marks the beginning of
    data section

    :ivar str file_name: File name
    :ivar int file_length: File length in bytes
    :ivar list[RecordList] table_data:
    :ivar int table_length: Length of table in bytes
    :ivar int table_record_length: Length of each record in bytes
    :ivar int table_rows: Number of rows in table

    :ivar list[object] data_parsed: List of parsed data values
    :ivar int data_offset: Data section offset

    :ivar OrderedDict columns: Shortened list of columns excluding intermediate
    columns
    :ivar OrderedDict columns_zip: Shortened list of columns excluding zipped
    columns
    :ivar OrderedDict columns_all: Complete list of columns, including all
    intermediate and virtual columns
    :ivar OrderedDict columns_data: List of all columns directly derived
    from the data
    :ivar OrderedDict table_columns: Used for mapping columns to indexes
    """
    _table_offset = 4
    _cast_table = {
        'bool': ['?', 1],
        'byte': ['b', 1],
        'ubyte': ['B', 1],
        'short': ['h', 2],
        'ushort': ['H', 2],
        'int': ['i', 4],
        'uint': ['I', 4],
        'long': ['q', 8],
        'ulong': ['Q', 8],
    }
    _data_magic_number = b'\xBB\xbb\xBB\xbb\xBB\xbb\xBB\xbb'

    def __init__(self, file_name, *args, use_dat_value=True, specification=None):
        self.data_parsed = []
        self.data_offset = 0
        self.file_length = 0
        self._file_raw = b''
        self.table_data = []

        self.table_length = 0
        self.table_record_length = 0
        self.table_rows = 0
        self.file_name = file_name

        #
        self.use_dat_value = use_dat_value

        # Process specification
        if specification is None:
            if file_name in _default_spec:
                specification = _default_spec[file_name]
            else:
                raise SpecificationError('No specification for "%s"' % file_name)
        else:
            specification = specification[file_name]
        self.specification = specification

        # Prepare the casts
        self.table_columns = OrderedDict()
        self.cast_size = 0
        self.cast_spec = []
        self.cast_row = []
        if specification:
            for i, key in enumerate(specification['columns_data']):
                k = specification['fields'][key]
                self.table_columns[key] = {'index': i, 'section': k}
                casts = []
                remainder = k['type']
                while remainder:
                    remainder, cast_type = self._get_cast_type(remainder)
                    casts.append(cast_type)
                self.cast_size += casts[0][1]

                self.cast_spec.append((k, casts))
                self.cast_row.append(casts[0][2])

            self.cast_row = '<' + ''.join(self.cast_row)

            for var in ('columns', 'columns_all', 'columns_zip', 'columns_data'):
                setattr(self, var, specification[var])
        else:
            s = configobj.Section(None, 0, None)
            s.name = 'Unparsed'
            self.table_columns.append(s)
            for var in ('columns', 'columns_all', 'columns_zip', 'columns_data'):
                setattr(self, var, OrderedDict([s.name, ]))

    def __iter__(self):
        return iter(self.table_data)

    def __getitem__(self, item):
        return self.table_data[item]

    def row_iter(self):
        return iter(self.table_data)

    def column_iter(self):
        for ci, column in enumerate(self.table_columns):
            yield [item[ci] for item in self]

    def _get_cast_type(self, caststr):
        size = None
        cast = None
        remainder = ''
        if caststr in self._cast_table:
            cast_type = 1
            size = self._cast_table[caststr][1]
            cast = self._cast_table[caststr][0]
        elif caststr == 'string':
            cast_type = 2
        elif caststr.startswith('ref|list|'):
            cast_type = 3
            size = 8
            cast = 'II'
            remainder = caststr[9:]
        elif caststr.startswith('ref|'):
            cast_type = 4
            size = 4
            cast = 'I'
            remainder = caststr[4:]
        return remainder, (cast_type, size, cast)

    def _cast_from_spec(self, specification, casts, parent=None, offset=None, data=None, queue_data=None):
        if casts[0][0] == 1:
            ivalue = data[0] if data else struct.unpack('<' + casts[0][2], self._file_raw[offset:offset+casts[0][1]])[0]

            if ivalue in (-0x1010102, 0xFEFEFEFE, -0x101010101010102, 0xFEFEFEFEFEFEFEFE):
                ivalue = None

            if self.use_dat_value:
                value = DatValue(ivalue, offset, casts[0][1], parent, specification)
            else:
                value = ivalue
        elif casts[0][0] == 2:
            # Beginning of the sequence, +1 to adjust for it
            offset_new = self._file_raw.find(b'\x00\x00\x00\x00', offset)
            # Account for 0 size strings
            if offset == offset_new:
                string = ''
            else:
                # It's possible that a string ends in \x00 and the next starts
                # with \x00
                # UTF-16 must be at least a multiple of 2
                while (offset_new-offset) % 2:
                    offset_new = self._file_raw.find(b'\x00\x00\x00\x00', offset_new+1)
                string = self._file_raw[offset:offset_new].decode('utf-16')
            # Store the offset including the null terminator
            if self.use_dat_value:
                value = DatValue(string, offset, offset_new-offset+4, parent, specification)
            else:
                value = string

        elif casts[0][0] >= 3:
            data = data if data else struct.unpack('<' + casts[0][2], self._file_raw[offset:offset+casts[0][1]])
            data_offset = data[-1] + self.data_offset

            # Instance..
            if self.use_dat_value:
                value = DatValue(data[0] if casts[0][0] == 4 else data, offset, casts[0][1], parent, specification)

                if casts[0][0] == 3:
                    value.children = []
                    for i in range(0, data[0]):
                        '''if offset < self._data_offset_current:
                            print(self._data_offset_current, offset)
                            raise SpecificationError("Overlapping offset for cast %s:%s" % (parent.is_list, casts[0]))'''
                        value.children.append(self._cast_from_spec(specification, casts[1:], value, data_offset+i*casts[1:][0][1]))
                elif casts[0][0] == 4:
                    value.child = self._cast_from_spec(specification, casts[1:], value, data_offset)
                self.data_parsed.append(value)
            else:
                if casts[0][0] == 3:
                    value = []
                    for i in range(0, data[0]):
                        value.append(self._cast_from_spec(specification, casts[1:], value, data_offset+i*casts[1:][0][1]))
                elif casts[0][0] == 4:
                    value = self._cast_from_spec(specification, casts[1:], None, data_offset)
        # TODO
        #if parent:
        #    self._data_offset_current = offset
        #    self.data_parsed.append(value)

        return value

    def _process_row(self, rowid):
        offset = 4 + rowid * self.table_record_length
        row_data = RecordList(self, rowid)
        data_raw = self._file_raw[offset:offset+self.table_record_length]

        # We don't have any data, return early
        if len(data_raw) == 0:
            return row_data

        if self.cast_spec:
            # Unpacking the entire row in one go will help breaking down the
            # function calls significantly
            row_unpacked = struct.unpack(self.cast_row, data_raw)
            i = 0
            for spec, casts in self.cast_spec:
                if casts[0][0] == 3:
                    cell_data = row_unpacked[i:i+2]
                    i += 1
                else:
                    cell_data = (row_unpacked[i], )
                row_data.append(self._cast_from_spec(spec, casts, data=cell_data, offset=offset))
                offset += casts[0][1]
                i += 1
        else:
            if self.use_dat_value:
                unparsed = DatValue(value=data_raw, offset=offset, size=self.table_record_length)
            else:
                unparsed = data_raw
            row_data.append(unparsed)
            offset += self.table_record_length

        return row_data

    def read(self, raw):
        # TODO consider memory issues for saving raw contents
        if isinstance(raw, bytes):
            self._file_raw = raw
        elif isinstance(raw, BytesIO):
            self._file_raw = raw.read()
        else:
            raise TypeError('Raw must be bytes or BytesIO instance, got %s' %
                            type)

        # Jump to last byte to get length
        self.file_length = len(self._file_raw)

        self.data_offset = self._file_raw.find(self._data_magic_number)

        if self.data_offset == -1:
            raise ValueError(
                'Did not find data magic number in "%(file)s"' % {
                    'file:': self.file_name,
                }
            )

        self.table_rows = struct.unpack('<I', self._file_raw[0:4])[0]
        self.table_length = self.data_offset - self._table_offset
        if self.table_rows > 0:
            self.table_record_length = self.table_length//self.table_rows
        elif self.table_rows == 0 and self.table_length == 0:
            self.table_record_length = 0
        else:
            #TODO
            raise ValueError("WTF")

        if self.specification is None:
            self.cast_size = self.table_record_length

        if self.cast_size != self.table_record_length:
            raise SpecificationError(
                '"%(name)s": Specification row size %(spec_size)s vs real size %(cast_size)s' % {
                    'name': self.file_name,
                    'spec_size': self.cast_size,
                    'cast_size': self.table_record_length
                }
            )

        self.table_data = []

        # Prepare data section
        self.data_parsed = list()

        for i in range(0, self.table_rows):
            self.table_data.append(self._process_row(i))

        return self.table_data

    def print_data(self):
        for row in self.table_data:
            print('Row: %s' % row.rowid)
            for k in row.keys():
                v = row[k]
                print('|- %s: %s' % (k, v))

    @deprecated
    def export_to_html(self, export_table=True, export_data=False):
        outstr = []
        if export_table:
            outstr.append('<table>')

            outstr.append('<thead>')
            outstr.append('<tr>')
            outstr.append('<th>')
            outstr.append('ROW')
            outstr.append('</th>')
            for key in self.specification['fields']:
                outstr.append('<th>')
                disp = self.specification['fields'][key]['display']
                if not disp:
                    disp = key
                outstr.append(disp)
                outstr.append('</th>')
            outstr.append('</tr>')
            outstr.append('</thead>')

            outstr.append('<tbody>')
            for row in self.table_data:
                outstr.append('<tr>')
                outstr.append('<th>')
                outstr.append(str(row.rowid))
                outstr.append('</th>')
                for dv in row:
                    outstr.append('<td>')
                    if self.use_dat_value:
                        outstr.append(str(dv.get_value()))
                    elif isinstance(dv, RecordList):
                        outstr.append(str(dv.rowid))
                    else:
                        outstr.append(str(dv))
                    outstr.append('</td>')
                outstr.append('</tr>')
            outstr.append('</tbody>')

            outstr.append('</table>')
        if export_data:
            outstr.append('<table>')

            outstr.append('<thead>')
            outstr.append('<tr>')
            outstr.append('</tr>')
            outstr.append('</thead>')

            outstr.append('<tbody>')
            outstr.append('</tbody>')

            outstr.append('</table>')
        return ''.join(outstr)


class DatFile(AbstractFileReadOnly):
    """
    Representation of a .dat file.

    :ivar reader:
    :type reader: DatReader
    """
    
    def __init__(self, file_name):
        """
        :param file_name: Name of the .dat file
        :type file_name: str
        """
        self._file_name = file_name
        self.reader = None

    def __repr__(self):
        return 'DatFile<%s>(file_name="%s")' % (hex(id(self)), self._file_name)

    def _read(self, buffer, *args, **kwargs):
        self.reader = DatReader(self._file_name, **kwargs)
        self.reader.read(buffer.read())

        return self.reader


@doc(doc=AbstractFileCache, prepend="""
Read dat files in a relational matter.

This acts both as a cache and as a way to easily access the instances.
""")
class RelationalReader(AbstractFileCache):
    FILE_TYPE = DatFile

    def __getitem__(self, item):
        """
        Shortcut that also appends Data/ if missing

        self[item] <==> read_file(item).reader
        """
        if not item.startswith('Data/'):
            item = 'Data/' + item

        return self.get_file(item).reader

    def _set_value(self, obj, other, key, offset):
        if obj is None:
            obj = None
        elif offset:
            obj = other[obj-offset]
        elif key:
            for row in other:
                if row[key] == obj:
                    obj = row
                    break
            if obj is not row:
                raise SpecificationError('Did not find proper value for foreign key %s' % key)
        else:
            obj = other[obj]
        return obj

    def _dv_set_value(self, value, other, key, offset):
        if value.is_pointer:
            self._dv_set_value(value.child, other, key, offset)
        elif value.is_list:
            [self._dv_set_value(dv, other, key, offset) for dv in value.children]
        else:
            value.value = self._set_value(value.value, other, key, offset)

        return value

    def _simple_set_value(self, value, other, key, offset):
        if isinstance(value, list):
            return [self._set_value(item, other, key, offset) for item in value]
        else:
            return self._set_value(value, other, key, offset)

    def _get_file_instance_args(self, file_name, *args, **kwargs):
        opts = super(RelationalReader, self)._get_file_instance_args(file_name)
        opts['file_name'] = file_name.replace('Data/', '')
        return opts

    def get_file(self, file_name):
        """
        Attempts to return a dat file from the cache and if it isn't available,
        reads it in.

        During the process any relations (i.e. fields that have a "key" to
        other .dat files specified) will be read. This will result in the
        appropriate fields being replaced by the related row.
        Note that a related row may be "None" if no key was specified in the
        read dat file.

        :param str file_name: The name of the .dat to read. Extension is required.
        :return: Returns the given DatFile instance
        :rtype: DatFile
        """
        if file_name in self.files:
            return self.files[file_name]

        df = self._create_instance(file_name)

        self.files[file_name] = df

        vf = self._dv_set_value if df.reader.use_dat_value else self._simple_set_value

        for key in df.reader.specification['fields']:
            other = df.reader.specification['fields'][key]['key']
            if not other:
                continue
            df_other_reader = self[other]

            key_id = df.reader.specification['fields'][key]['key_id']
            key_offset = df.reader.specification['fields'][key]['key_offset']

            index = df.reader.table_columns[key]['index']

            for i, row in enumerate(df.reader.table_data):
                df.reader.table_data[i][index] = vf(
                    row[index],
                    df_other_reader,
                    key_id,
                    key_offset,
                )

        return df


# =============================================================================
# Functions
# =============================================================================


def load_spec(path=None):
    """
    Loads a specification that can be used for the dat files. It will be
    verified and errors will be raised accordingly if any errors occur.

    :param str path: If specified, read the specified file as config
    :return: returns the ConfigObj of the read file.
    :rtype: :class:`ConfigObj`

    :raises SpecificationError: if key or key_id point to invalid files or
    keys respectively
    """
    if path is None:
        path = DAT_SPECIFICATION
    spec = configobj.ConfigObj(infile=path, configspec=DAT_SPECIFICATION_CONFIGSPEC)
    spec.validate(validate.Validator())

    for file_name, file_spec in spec.items():
        columns = OrderedDict()
        for field_name, field in file_spec['fields'].items():
            # Validation
            other = field['key']
            if other:
                if other not in spec:
                    raise SpecificationError(
                        '%(dat_file)s->%(field)s->key: %(other)s not in '
                        'specification' % {
                            'dat_file': file_name,
                            'field': file_name,
                            'other': other,
                        }
                    )

                other_key = field['key_id']
                if other_key and other_key not in spec[other]['fields']:
                    raise SpecificationError(
                        '%(dat_file)s->%(field)s->key_id: %(other)s->'
                        '%(other_key)s not in specification' % {
                            'dat_file': file_name,
                            'field': file_name,
                            'other': other,
                            'other_key': other_key,
                        }
                    )
            # Extra fields
            columns[field_name] = None

        columns_zip = OrderedDict(columns)
        columns_all = OrderedDict(columns)
        columns_data = OrderedDict(columns)

        for field_name, field in file_spec['virtual_fields'].items():
            # Validation
            if field_name in file_spec['fields']:
                raise SpecificationError(
                    '%(dat_file)s->virtual_fields->%(field)s use the same name '
                    'as a key specified in %(dat_file)s->fields' %
                    {
                        'dat_file': file_name,
                        'field': field_name,
                    }
                )

            if not field['fields']:
                raise SpecificationError(
                    '%(dat_file)s->virtual_fields->%(field)s->fields is empty' %
                    {
                        'dat_file': file_name,
                        'field': field_name,
                    }
                )

            for other_field in field['fields']:
                if other_field not in file_spec['fields'] and \
                                other_field not in file_spec['virtual_fields']:
                    raise SpecificationError(
                        '%(dat_file)s->virtual_fields->%(field)s->fields: '
                        'Field "%(other_field)s" does not exist' %
                        {
                            'dat_file': file_name,
                            'field': field_name,
                            'other_field': other_field,
                        }
                    )
                if field['zip'] and other_field in file_spec['fields'] and \
                        not file_spec['fields'][other_field]['type'].startswith(
                            'ref|list'):
                    raise SpecificationError(
                        '%(dat_file)s->virtual_fields->%(field)s->zip: The zip '
                        'option requires "%(other_field)s" to be a list' %
                        {
                            'dat_file': file_name,
                            'field': field_name,
                            'other_field': other_field,
                        }
                    )
            # Extra fields
            columns_all[field_name] = None
            columns[field_name] = None
            if field['zip']:
                columns_zip[field_name] = None

            for f in field['fields']:
                del columns[f]
                if field['zip']:
                    del columns_zip[f]

        for var in ('columns', 'columns_all', 'columns_zip', 'columns_data'):
            file_spec[var] = locals()[var]

    return spec


def reload_default_spec():
    """
    Reloads the default specification.
    """
    global _default_spec
    _default_spec = load_spec()

# =============================================================================
# Init
# =============================================================================

reload_default_spec()

