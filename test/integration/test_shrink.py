import elasticsearch
import curator
import os
import json
import string, random, tempfile
from click import testing as clicktest
from mock import patch, Mock

from . import CuratorTestCase
from . import testvars as testvars

import logging
logger = logging.getLogger(__name__)

host, port = os.environ.get('TEST_ES_SERVER', 'localhost:9200').split(':')
port = int(port) if port else 9200

shrink = ('---\n'
'actions:\n'
'  1:\n'
'    description: "Act on indices as filtered"\n'
'    action: shrink\n'
'    options:\n'
'      shrink_node: {0}\n'
'      node_filters:\n'
'          {1}: {2}\n'
'      number_of_shards: {3}\n'
'      number_of_replicas: {4}\n'
'      shrink_prefix: {5}\n'
'      shrink_suffix: {6}\n'
'      delete_after: {7}\n'
'    filters:\n'
'      - filtertype: pattern\n'
'        kind: prefix\n'
'        value: my\n')

no_permit_masters = ('---\n'
'actions:\n'
'  1:\n'
'    description: "Act on indices as filtered"\n'
'    action: shrink\n'
'    options:\n'
'      shrink_node: {0}\n'
'      number_of_shards: {1}\n'
'      number_of_replicas: {2}\n'
'      shrink_prefix: {3}\n'
'      shrink_suffix: {4}\n'
'      delete_after: {5}\n'
'    filters:\n'
'      - filtertype: pattern\n'
'        kind: prefix\n'
'        value: my\n')

with_extra_settings = ('---\n'
'actions:\n'
'  1:\n'
'    description: "Act on indices as filtered"\n'
'    action: shrink\n'
'    options:\n'
'      shrink_node: {0}\n'
'      node_filters:\n'
'          {1}: {2}\n'
'      number_of_shards: {3}\n'
'      number_of_replicas: {4}\n'
'      shrink_prefix: {5}\n'
'      shrink_suffix: {6}\n'
'      delete_after: {7}\n'
'      extra_settings:\n'
'        settings:\n'
'          {8}: {9}\n'
'        aliases:\n'
'          my_alias: {10}\n'
'      post_allocation:\n'
'          allocation_type: {11}\n'
'          key: {12}\n'
'          value: {13}\n'
'    filters:\n'
'      - filtertype: pattern\n'
'        kind: prefix\n'
'        value: my\n')

class TestCLIShrink(CuratorTestCase):
    def builder(self, action_args):
        self.idx = 'my_index'
        suffix = '-shrunken'
        self.target = '{0}{1}'.format(self.idx, suffix)
        self.create_index(self.idx, shards=2)
        self.add_docs(self.idx)
        self.write_config(self.args['configfile'], testvars.client_config.format(host, port))
        self.write_config(self.args['actionfile'], action_args)
        test = clicktest.CliRunner()
        self.result = test.invoke(
            curator.cli,
            [
                '--config', self.args['configfile'],
                self.args['actionfile']
            ],
        )
    def test_shrink(self):
        suffix = '-shrunken'
        self.builder(
            shrink.format(
                'DETERMINISTIC',
                'permit_masters',
                'True',
                1,
                0,
                '',
                suffix,
                'True'
            )
        )
        indices = curator.get_indices(self.client)
        self.assertEqual(1, len(indices)) # Should only have `my_index-shrunken`
        self.assertEqual(indices[0], self.target)
    def test_permit_masters_false(self):
        suffix = '-shrunken'
        self.builder(
            no_permit_masters.format(
                'DETERMINISTIC',
                1,
                0,
                '',
                suffix,
                'True'
            )
        )
        indices = curator.get_indices(self.client)
        self.assertEqual(1, len(indices)) # Should only have `my_index-shrunken`
        self.assertEqual(indices[0], self.idx)
        self.assertEqual(self.result.exit_code, 1)
    def test_shrink_non_green(self):
        suffix = '-shrunken'
        self.client.indices.create(
            index='just_another_index',
            body={'settings': {'number_of_shards': 1, 'number_of_replicas': 1}}
        )
        self.builder(
            shrink.format(
                'DETERMINISTIC',
                'permit_masters',
                'True',
                1,
                0,
                '',
                suffix,
                'True'
            )
        )
        indices = curator.get_indices(self.client)
        self.assertEqual(2, len(indices)) # Should have two indices, and a failed exit code (non-green)
        self.assertEqual(self.result.exit_code, 1)
    def test_shrink_with_extras(self):
        suffix = '-shrunken'
        allocation_type = 'exclude'
        key = '_name'
        value = 'not_this_node'
        self.builder( 
            with_extra_settings.format(
                'DETERMINISTIC',
                'permit_masters',
                'True',
                1,
                0,
                '',
                suffix,
                'False',
                'index.codec',
                'best_compression',
                dict(),
                allocation_type,
                key,
                value
            )
        )
        indices = curator.get_indices(self.client)
        self.assertEqual(2, len(indices)) # Should only have `my_index-shrunken`
        settings = self.client.indices.get_settings()
        self.assertTrue(settings[self.target]['settings']['index']['routing']['allocation'][allocation_type][key] == value)
        self.assertTrue(settings[self.idx]['settings']['index']['routing']['allocation']['require']['_name'] == '')
        self.assertEqual(settings[self.target]['settings']['index']['codec'], 'best_compression')
        self.assertTrue(self.client.indices.exists_alias(index=self.target, name='my_alias'))
