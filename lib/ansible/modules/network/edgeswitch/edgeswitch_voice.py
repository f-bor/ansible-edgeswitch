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
module: edgeswitch_voice
version_added: "2.8"
author: "Frederic Bor (@f-bor)"
short_description: Manage voice feature on Ubiquiti Edgeswitch network devices
description:
  - This module provides declarative management of voice feature
    on Ubiquiti Edgeswitch network devices.
notes:
  - Tested against Edgemax 1.7.4
  - Voice features can only be enabled on physical interfaces
options:
  vlan_id:
    description:
      - ID of the voice VLAN. Range 1-4093.
  interfaces:
    description:
      - List of interfaces that should be associated to the voice VLAN.
        C(all) for all the switch interfaces. Accept range of interfaces.
  dscp:
    description:
      - Voice vlan DSCP.
  lldp:
    description:
      - List of LLDP options to enable on interfaces.
    choices: ['transmit', 'receive', 'med']
  state:
    description:
      - Action to apply on the voice VLAN configuration.
    default: present
    choices: ['present', 'absent']
  aggregate:
    description: List of voices VLAN definitions.
"""

EXAMPLES = """
- name: Setup voice vlan
  edgeswitch_voice:
    vlan_id: 100
    dscp: 46
    state: present
    interfaces:
      - 0/1
      - 0/3-0/6

- name: Remove voice vlan configuration
  edgeswitch_voice:
    state: absent
    interfaces:
      - all
"""

RETURN = """
commands:
  description: The list of configuration mode commands to send to the device
  returned: always
  type: list
  sample:
    - interface 0/1
    - voice vlan 100
    - voice vlan dscp 46
    - lldp transmit
    - lldp receive
    - lldp med

  sample:
    - interface 0/1
    - no voice vlan
    - no voice vlan dscp
"""

import re

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.network.edgeswitch.edgeswitch import get_interfaces_config, load_config, build_aggregate_spec, map_params_to_obj


def map_to_commands_interface(vlan_id, dscp, lldp, state, port):
    commands = []
    if state == 'present':
        if port['voice_vlan'] != vlan_id:
            commands.append('voice vlan {}' + vlan_id)

        if port['voice_dscp'] != dscp:
            commands.append('voice vlan dscp ' + dscp)

        for ltype in lldp:
            if ltype not in port['lldp']:
                commands.append("lldp " + ltype)

    elif state == 'absent':
        if port['voice_vlan'] != 'no':
            commands.append('no voice vlan')

        if port['voice_dscp'] != 'no':
            commands.append('no voice vlan dscp')

    return commands


def map_to_commands(want, ports, module):
    commands = list()

    for w in want:
        interfaces_cmd = {}
        vlan_id = str(w['vlan_id'])
        dscp = w['dscp']
        interfaces = w['interfaces']
        lldp = w['lldp']
        state = w['state']
        if state == 'present' and vlan_id == 'None':
            module.fail_json(msg="state is 'present' but the following is missing: vlan_id")
            return

        for i in interfaces:
            if i == 'all':
                for key, value in ports.items():
                    if not key.startswith('0/'):
                        continue

                    port = ports[key]
                    interfaces_cmd[key] = map_to_commands_interface(vlan_id, dscp, lldp, state, port)

            else:
                match = re.search(r'0\/(\d+)-0\/(\d+)', i)
                if match:
                    for x in range(int(match.group(1)), int(match.group(2)) + 1):
                        key = '0/' + str(x)
                        port = ports[key]
                        interfaces_cmd[key] = map_to_commands_interface(vlan_id, dscp, lldp, state, port)
                else:
                    port = ports[i]
                    interfaces_cmd[i] = map_to_commands_interface(vlan_id, dscp, lldp, state, port)

        for i, t in interfaces_cmd.items():
            if len(t):
                commands.append('interface {0}'.format(i))
                commands.extend(t)

    return commands


def map_config_to_obj(module):
    have = {}
    ic = get_interfaces_config(module)
    for key, value in ic.items():
        cfg = '\n'.join(value)
        match = re.search('interface (.*)\n', cfg, re.M)
        if not match:
            continue

        # ling aggregation does not support voice vlan
        iname = match.group(1)
        if iname.startswith("lag"):
            continue

        port = {}
        have[iname] = port
        match = re.search(r'voice vlan (\d+)', cfg, re.M)
        if match:
            port['voice_vlan'] = match.group(1)
        else:
            port['voice_vlan'] = 'no'

        match = re.search(r'voice vlan dscp (\d+)', cfg, re.M)
        if match:
            port['voice_dscp'] = match.group(1)
        else:
            port['voice_dscp'] = 'no'

        port['lldp'] = re.findall(r'lldp ([\w\-\ ]+)', cfg)

    return have


def main():
    """ main entry point for module execution
    """
    element_spec = dict(
        vlan_id=dict(type='int'),
        dscp=dict(),
        interfaces=dict(type='list'),
        lldp=dict(type='list',
                  choices=['transmit', 'receive', 'med']),
        state=dict(default='present',
                   choices=['present', 'absent'])
    )

    required_one_of = [['interfaces', 'aggregate']]
    mutually_exclusive = [['interfaces', 'aggregate']]

    module = AnsibleModule(argument_spec=build_aggregate_spec(element_spec, ['interfaces']),
                           required_one_of=required_one_of,
                           supports_check_mode=True,
                           mutually_exclusive=mutually_exclusive)

    result = {'changed': False}

    want = map_params_to_obj(module)
    have = map_config_to_obj(module)

    commands = map_to_commands(want, have, module)
    result['commands'] = commands

    if commands:
        if not module.check_mode:
            load_config(module, commands)
        result['changed'] = True

    module.exit_json(**result)


if __name__ == '__main__':
    main()
