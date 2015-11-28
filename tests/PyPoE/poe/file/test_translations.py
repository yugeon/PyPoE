"""
Tests for PyPoE.poe.file.translations

Overview
-------------------------------------------------------------------------------

+----------+------------------------------------------------------------------+
| Path     | tests/PyPoE/poe/file/test_translations.py                        |
+----------+------------------------------------------------------------------+
| Version  | 1.0.0a0                                                          |
+----------+------------------------------------------------------------------+
| Revision | $Id$                                                             |
+----------+------------------------------------------------------------------+
| Author   | Omega_K2                                                         |
+----------+------------------------------------------------------------------+

Description
-------------------------------------------------------------------------------

Tests for translations.py

Agreement
-------------------------------------------------------------------------------

See PyPoE/LICENSE

TODO
-------------------------------------------------------------------------------

- Tests for the individual classes and functions, not just the results
"""

# =============================================================================
# Imports
# =============================================================================

# Python
import os

# 3rd Party
import pytest

# self
from PyPoE.poe.file import translations

# =============================================================================
# Setup
# =============================================================================

cur_dir = os.path.split(os.path.realpath(__file__))[0]
data_dir = os.path.join(cur_dir, '_data')
dbase_path = os.path.join(data_dir, 'Metadata', 'descriptions_base.txt')
dextended_path = os.path.join(data_dir, 'Metadata', 'descriptions_extended.txt')

data = {
    'base': (
        # Size, Unique ID,  values
        (1, 1, ((1, ), )),
        (1, 2, ((40, ), (1, ))),
        (1, 3, ((1, ), )),
        (2, 1, ((1, 99), (99, 1), (99, 99))),
        (3, 1, ((50, 1, 1), (100, 1, 1))),
    ),
    'quantifier': (

    ),
}

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def dbase():
    tf = translations.TranslationFile()
    tf.read(dbase_path)
    return tf


@pytest.fixture
def dextended():
    tf = translations.TranslationFile(base_dir=data_dir)
    tf.read(dextended_path)
    return tf


@pytest.fixture
def tcache():
    return translations.TranslationFileCache(path_or_ggpk=data_dir)


def get_test(size, unid, nresults, values):
    tags = ['tag_size%s_uq%s_no%s' % (size, unid, i) for i in range(1, size+1)]
    results = ['tag_size%s_uq%s_v%s:%s' % (size, unid, i, ' %s'*size) for i in range(1, nresults+1)]

    for i, v in enumerate(results):
        results[i] = v % values[i]

    return tags, results

# =============================================================================
# Tests
# =============================================================================


class TestTranslation:
    def build_get_translation_data(self=None):
        test_data = []
        for size, unique_id, values in data['base']:
            tags, results = get_test(size, unique_id, len(values), values)
            for i, v in enumerate(values):
                test_data.append((tags, v, results[i]))

        return test_data

    def test_read(self, dbase):
        pass

    def test_read_with_include(self, dextended):
        pass

    @pytest.mark.parametrize('tags,values,result', build_get_translation_data())
    def test_get_translation_simple(self, dbase, tags, values, result):
        assert dbase.get_translation(tags, values)[0] == result

    @pytest.mark.parametrize('tags,values,string', build_get_translation_data())
    def test_reverse_translation_simple(self, dbase, string, values, tags):
        trr = dbase.reverse_translation(string)
        # Returns a list of matching translations/values, but our test data
        # should be unique
        assert trr.values[0] == list(values)
        assert trr.translations[0].ids == tags

    def test_skip(self, dbase):
        tags = ['tag_skip_size2_uq1_no1', 'tag_skip_size2_uq1_no2']
        values = [1, 50]
        result = 'tag_skip_size2_uq1_v1: 50'

        assert dbase.get_translation(tags, values)[0] == result, 'Value skip normal failed'

        trr = dbase.reverse_translation(result)

        assert trr.translations[0].ids == tags, 'Value skip reverse failed: incorrect tags'
        assert trr.values[0] == values, 'Value skip failed reverse: incorrect values'


class TestTranslationFileCache:
    def test_init(self, tcache):
        pass

    def test_get_file(self, tcache, dbase, dextended):
        assert tcache.get_file('Metadata/descriptions_base.txt') == dbase, 'Files should be identical'
        assert tcache.get_file('Metadata/descriptions_extended.txt') == dextended, 'Files should be identical'

    def test_getitem(self, tcache, dbase, dextended):
        assert tcache['descriptions_base.txt'] == dbase, 'Files should be identical'
        assert tcache['descriptions_extended.txt'] == dextended, 'Files should be identical'

    def test_is_cache_working(self, tcache):
        a = tcache['descriptions_extended.txt']
        # Should have cached the included file
        tcache.files['Metadata/descriptions_base.txt']

        assert tcache['descriptions_extended.txt'] is a, 'Cache should return identical object'


'''def test_tag1_value1():
    t = ['life_regeneration_rate_+%']
    values = {
        'life_regeneration_rate_+%': [-2, ],
    }
    _expected_result_assert(t, values)

def test_tag2_value2():
    t = ['minimum_added_fire_damage_per_active_buff', 'maximum_added_fire_damage_per_active_buff']
    values = {
        'Adds 1 maximum Fire Damage per Buff on You': [0, 1],
        'Adds 1 minimum Fire Damage per Buff on You': [1, 0],
        'Adds 1-1 Fire Damage per Buff on You': [1, 1],
    }
    _expected_result_assert(t, values)

def test_tag2_value1():
    t = ['base_chance_to_freeze_%']
    values = {
        '50% chance to Freeze': [50, ],
        '99% chance to Freeze': [99,],
        'Always Freeze': [100,],
    }
    _expected_result_assert(t, values)'''