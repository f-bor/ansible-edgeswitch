# (c) 2018 Red Hat Inc.
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from units.compat.mock import patch
from ansible.modules.network.edgeswitch import edgeswitch_interface
from units.modules.utils import set_module_args
from .edgeswitch_module import TestEdgeswitchModule, load_fixture


class TestEdgeswitchInterfaceModule(TestEdgeswitchModule):

    module = edgeswitch_interface

    def setUp(self):
        super(TestEdgeswitchInterfaceModule, self).setUp()

        self.mock_run_commands = patch('ansible.modules.network.edgeswitch.edgeswitch_interface.run_commands')
        self.run_commands = self.mock_run_commands.start()

        self.mock_get_config = patch('ansible.module_utils.network.edgeswitch.edgeswitch.get_config')
        self.get_config = self.mock_get_config.start()

        self.mock_load_config = patch('ansible.modules.network.edgeswitch.edgeswitch_interface.load_config')
        self.load_config = self.mock_load_config.start()

    def tearDown(self):
        super(TestEdgeswitchInterfaceModule, self).tearDown()
        self.mock_run_commands.stop()
        self.mock_get_config.stop()
        self.mock_load_config.stop()

    def load_fixtures(self, commands=None):
        def load_from_file(*args, **kwargs):
            module, commands = args
            output = list()

            for command in commands:
                if command.startswith('interface ') or command == 'exit':
                    output.append('')
                else:
                    filename = str(command).split(' | ')[0].replace(' ', '_').replace('/', '_')
                    output.append(load_fixture('edgeswitch_interface_%s' % filename))
            return output

        self.get_config.return_value = load_fixture('edgeswitch_interface_config.cfg')
        self.run_commands.side_effect = load_from_file
        self.load_config.return_value = {}

    def test_edgeswitch_interface_up(self):
        set_module_args({'name': '0/2', 'enabled': True})
        result = self.execute_module(changed=True)
        self.assertEqual(result['commands'], ['interface 0/2', 'no shutdown'])

    def test_edgeswitch_interface_down(self):
        set_module_args({'name': '0/3', 'enabled': False})
        result = self.execute_module(changed=True)
        self.assertEqual(result['commands'], ['interface 0/3', 'shutdown'])

    def test_edgeswitch_interface_description(self):
        set_module_args({'name': '0/3', 'description': 'interface-test'})
        result = self.execute_module(changed=True)
        self.assertEqual(result['commands'], ['interface 0/3', 'description \'interface-test\''])

    def test_edgeswitch_interface_mtu(self):
        set_module_args({'name': '0/3', 'mtu': 9216})
        result = self.execute_module(changed=True)
        self.assertEqual(result['commands'], ['interface 0/3', 'mtu 9216'])

    def test_edgeswitch_interface_speed_idempotence(self):
        set_module_args({'name': '0/3', 'speed': 'auto'})
        result = self.execute_module(changed=False)
        self.assertEqual(result['commands'], [])
