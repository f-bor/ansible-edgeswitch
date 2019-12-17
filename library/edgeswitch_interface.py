#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2018, Ansible by Red Hat, inc
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = """
---
module: edgeswitch_interface
version_added: "2.8"
author: "Frederic Bor (@f-bor)"
short_description: Manage Interface on Ubiquiti edgeswitch
description:
  - This module provides declarative management of Interfaces
    on Ubiquiti Edgeswitch devices.
notes:
  - Tested against edgeswitch 1.7.4
options:
  name:
    description:
      - Name of the interface to be configured on remote device.
    required: true
  description:
    description:
      - Description of interface.
  enabled:
    description:
      - Interface link status. If the value is I(True) the interface state will be enabled,
        else if value is I(False) interface will be in disable (shutdown) state.
    required: False
    type: bool
  speed:
    description:
      - This option configures speed ant autonegotiation for the interface
        given in C(name) option.
  mtu:
    description:
      - Maximum size of transmit packet, must be between 1518 and 9216.
  aggregate:
    description: List of interfaces definitions.

"""

EXAMPLES = """
- name: configure interface
  edgeswitch_interface:
    name: 0/2
    description: test-interface
    speed: 100 half-duplex
    mtu: 9216

- name: make interface up
  edgeswitch_interface:
    name: 0/2
    enabled: True

- name: make interface down
  edgeswitch_interface:
    name: 0/2
    enabled: False

- name: Set interfaces using aggregate
  edgeswitch_interface:
    aggregate:
      - { name: 0/7, mtu: 9216, description: test-interface-1 }
      - { name: 0/8, mtu: 9216, description: test-interface-2 }
    speed: auto
    enabled: True

"""

RETURN = """
commands:
  description: The list of configuration mode commands to send to the device.
  returned: always, except for the platforms that use Netconf transport to manage the device.
  type: list
  sample:
  - interface 0/2
  - description 'test-interface'
  - speed 100 half-duplex
  - mtu 9216
"""
import re

from ansible.module_utils._text import to_text
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.network.edgeswitch.edgeswitch import get_interfaces_config, load_config, run_commands, build_aggregate_spec
from ansible.module_utils.network.common.config import NetworkConfig


def validate_mtu(value, module):
    if value and not 1518 <= int(value) <= 9216:
        module.fail_json(msg='mtu must be between 1518 and 9216')


def validate_param_values(module, obj, param=None):
    if param is None:
        param = module.params
    for key in obj:
        # validate the param value (if validator func exists)
        validator = globals().get('validate_%s' % key)
        if callable(validator):
            validator(param.get(key), module)


def parse_shutdown(cfg):
    match = re.search(r'^shutdown', '\n'.join(cfg), re.M)
    if match:
        return True
    else:
        return False


def parse_config_argument(cfg, arg, default=None):
    match = re.search(r'%s (.+)$' % arg, '\n'.join(cfg), re.M)
    if match:
        return match.group(1)
    return default


def parse_quoted_config_argument(cfg, arg=None):
    match = re.search(r'%s \'(.+)\'$' % arg, '\n'.join(cfg), re.M)
    if match:
        return match.group(1)


def search_obj_in_list(name, lst):
    for o in lst:
        if o['name'] == name:
            return o

    return None


def get_running_mtu(interface, module):
    cfg = run_commands(module, ['show interface ethernet ' + interface])[0]
    match = re.search(r'Max Frame Size\.+ (\d+)', cfg, re.M)
    if match:
        return match.group(1)


def map_config_to_obj(module):
    interfaces = get_interfaces_config(module)

    have = list()

    for key, value in interfaces.items():
        obj = {
            'name': parse_config_argument(value, 'interface'),
            'description': parse_quoted_config_argument(value, 'description'),
            'speed': parse_config_argument(value, 'speed', 'auto'),
            'mtu': parse_config_argument(value, 'mtu'),
            'disable': True if parse_shutdown(value) else False
        }
        have.append(obj)
    return have


def map_params_to_obj(module):
    obj = []
    aggregate = module.params.get('aggregate')
    if aggregate:
        for item in aggregate:
            for key in item:
                if item.get(key) is None:
                    item[key] = module.params[key]

            validate_param_values(module, item, item)
            d = item.copy()

            if 'enabled' in d and d['enabled'] is not None:
                if d['enabled']:
                    d['disable'] = False
                else:
                    d['disable'] = True

            obj.append(d)

    else:
        params = {
            'name': module.params['name'],
            'description': module.params['description'],
            'speed': module.params['speed'],
            'mtu': module.params['mtu'],
        }

        validate_param_values(module, params)
        if 'enabled' in module.params and module.params['enabled'] is not None:
            if module.params['enabled']:
                params.update({'disable': False})
            else:
                params.update({'disable': True})

        obj.append(params)
    return obj


def map_obj_to_commands(updates, module, warnings):
    commands = list()
    want, have = updates

    for w in want:
        cmds = []
        name = w['name']
        speed = w['speed']
        description = w['description']
        mtu = w['mtu']

        obj_in_have = search_obj_in_list(name, have)
        if obj_in_have is None:
            warnings.append('interface {0} does not exist on target'.format(name))
            continue

        running_mtu = obj_in_have.get('mtu')
        if mtu and not running_mtu:
            running_mtu = get_running_mtu(name, module)
        if mtu != running_mtu:
            cmds.append('mtu {0}'.format(mtu))

        if description:
            if description != obj_in_have.get('description'):
                cmds.append('description \'{0}\''.format(description))
        elif obj_in_have.get('description'):
            cmds.append('no description')

        if speed and speed != obj_in_have.get('speed'):
            cmds.append('speed ' + speed)

        if 'disable' in w and w['disable'] != obj_in_have.get('disable'):
            if w['disable']:
                cmds.append('shutdown')
            else:
                cmds.append('no shutdown')

        if len(cmds) > 0:
            commands.append('interface ' + name)
            commands.extend(cmds)

    return commands


def main():
    """ main entry point for module execution
    """

    element_spec = dict(
        name=dict(),
        description=dict(),
        speed=dict(),
        mtu=dict(),
        enabled=dict(required=False, type='bool'),
    )

    argument_spec = build_aggregate_spec(
        element_spec,
        ['name']
    )

    required_one_of = [['name', 'aggregate']]
    mutually_exclusive = [['name', 'aggregate']]

    module = AnsibleModule(argument_spec=argument_spec,
                           required_one_of=required_one_of,
                           mutually_exclusive=mutually_exclusive,
                           supports_check_mode=True)

    result = {'changed': False}

    want = map_params_to_obj(module)
    have = map_config_to_obj(module)

    warnings = []
    commands = map_obj_to_commands((want, have), module, warnings)
    result['commands'] = commands
    result['warnings'] = warnings

    if commands:
        if not module.check_mode:
            load_config(module, commands)
        result['changed'] = True

    module.exit_json(**result)


if __name__ == '__main__':
    main()
