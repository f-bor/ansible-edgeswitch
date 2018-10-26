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
module: edgeswitch_vlan
version_added: "2.8"
author: "Frederic Bor (@f-bor)"
short_description: Manage VLANs on Ubiquiti Edgeswitch network devices
description:
  - This module provides declarative management of VLANs
    on Ubiquiti Edgeswitch network devices.
notes:
  - Tested against edgeswitch 1.7.4
  - This module use native Ubiquiti vlan syntax, and does not support switchport compatibility syntax.
    For clarity, it is strongly advised to not use both syntaxes on the same interface.
  - Edgeswitch does not support changing name of VLAN 1
  - As auto_tag, auto_untag and auto_exclude are default settings for all interfaces, they are mutually exclusive

options:
  name:
    description:
      - Name of the VLAN.
  vlan_id:
    description:
      - ID of the VLAN. Range 1-4093.
  tagged_interfaces:
    description:
      - List of interfaces that should accept and transmit tagged frames for the VLAN.
        Accept range of interfaces. Use C(all) to configure all the switch interfaces.
  untagged_interfaces:
    description:
      - List of interfaces that should accept untagged frames and transmit them tagged
        for the VLAN.
        Accept range of interfaces. Use C(all) to configure all the switch interfaces.
  excluded_interfaces:
    description:
      - List of interfaces that should be excluded of the VLAN.
        Accept range of interfaces. Use C(all) to configure all the switch interfaces.
  auto_tag:
    description:
      - Each of the switch interfaces will be set to accept and transmit
        untagged frames for I(vlan_id) unless defined in I(*_interfaces).
        This is a default setting for all switch interfaces.
    type: bool
  auto_untag:
    description:
      - Each of the switch interfaces will be set to accept untagged frames and
        transmit them tagged into I(vlan_id) unless defined in I(*_interfaces).
        This is a default setting for all switch interfaces.
    type: bool
  auto_exclude:
    description:
      - Each of the switch interfaces will be excluded from I(vlan_id)
        unless defined in I(*_interfaces).
        This is a default setting for all switch interfaces.
    type: bool
  aggregate:
    description: List of VLANs definitions.
  purge:
    description:
      - Purge VLANs not defined in the I(aggregate) parameter.
    default: no
    type: bool
  state:
    description:
      - action on the VLAN configuration.
    default: present
    choices: ['present', 'absent']
"""

EXAMPLES = """
- name: Create vlan
  edgeswitch_vlan:
    vlan_id: 100
    name: voice
    action: present

- name: Add interfaces to VLAN
  edgeswitch_vlan:
    vlan_id: 100
    tagged_interfaces:
      - 0/1
      - 0/4-0/6

- name: setup three vlans and delete the rest
  edgeswitch_vlan:
    purge: true
    aggregate:
      - { vlan_id: 1, name: default, auto_untag: true, excluded_interfaces: 0/45-0/48 }
      - { vlan_id: 100, name: voice, auto_tag: true }
      - { vlan_id: 200, name: video, auto_exclude: true, untagged_interfaces: 0/45-0/48, tagged_interfaces: 0/46 }

- name: Delete vlan
  edgeswitch_vlan:
    vlan_id: 100
    state: absent
"""

RETURN = """
commands:
  description: The list of configuration mode commands to send to the device
  returned: always
  type: list
  sample:
    - vlan database
    - vlan 100
    - vlan name 100 "test vlan"
    - exit
    - interface 0/1
    - vlan pvid 50
    - vlan participation include 50
    - vlan participation include 100
    - vlan tagging 100
    - vlan participation exclude 200
    - no vlan tagging 200
"""

import re
import time


from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.network.edgeswitch.edgeswitch import load_config, run_commands
from ansible.module_utils.network.edgeswitch.edgeswitch import build_aggregate_spec, map_params_to_obj


def search_obj_in_list(vlan_id, lst):
    for o in lst:
        if o['vlan_id'] == str(vlan_id):
            return o


def map_vlans_to_commands(updates, module):
    commands = list()
    want, have = updates
    purge = module.params['purge']

    for w in want:
        vlan_id = w['vlan_id']
        name = w['name']
        state = w['state']

        obj_in_have = search_obj_in_list(vlan_id, have)

        if state == 'absent':
            if obj_in_have:
                commands.append('no vlan {0}'.format(vlan_id))

        elif state == 'present':
            if not obj_in_have:
                commands.append('vlan {0}'.format(vlan_id))
                if name:
                    commands.append('vlan name {0} "{1}"'.format(vlan_id, name))
            else:
                if name:
                    if name != obj_in_have['name']:
                        commands.append('vlan name {0} "{1}"'.format(vlan_id, name))

    if purge:
        for h in have:
            obj_in_want = search_obj_in_list(h['vlan_id'], want)
            # you can't delete vlan 1 on Edgeswitch
            if not obj_in_want and h['vlan_id'] != '1':
                commands.append('no vlan {0}'.format(h['vlan_id']))

    if commands:
        commands.insert(0, 'vlan database')
        commands.append('exit')

    return commands


def map_interfaces_to_commands(want, ports, module):
    def set_interfaces(interfaces_param, interfaces, action):
        if interfaces_param:
            for i in interfaces_param:
                match = re.search(r'(\d+)\/(\d+)-(\d+)\/(\d+)', i)
                if match:
                    for x in range(int(match.group(2)), int(match.group(4)) + 1):
                        interfaces['{0}/{1}'.format(match.group(1), x)] = action
                else:
                    interfaces[i] = action

    commands = list()
    purge = module.params['purge']

    interfaces_cmds = {}

    for w in want:
        state = w['state']
        if state != 'present':
            continue

        interfaces = {}
        auto_tag = w['auto_tag']
        auto_untag = w['auto_untag']
        auto_exclude = w['auto_exclude']
        vlan_id = w['vlan_id']
        tagged_interfaces = w['tagged_interfaces']
        untagged_interfaces = w['untagged_interfaces']
        excluded_interfaces = w['excluded_interfaces']

        for key, value in ports.items():
            if auto_tag:
                interfaces[key] = 'tag'
            elif auto_exclude:
                if vlan_id not in value['forbidden_vlans']:
                    interfaces[key] = 'exclude'
            elif auto_untag:
                interfaces[key] = 'untag'

        set_interfaces(tagged_interfaces, interfaces, 'tag')
        set_interfaces(untagged_interfaces, interfaces, 'untag')
        set_interfaces(excluded_interfaces, interfaces, 'exclude')

        for i, t in interfaces.items():
            try:
                cmds = interfaces_cmds[i]
            except KeyError:
                cmds = []
                interfaces_cmds[i] = cmds

            port = ports[i]
            if t == 'exclude':
                if vlan_id not in port['forbidden_vlans']:
                    cmds.append('vlan participation exclude {0}'.format(vlan_id))
                    cmds.append('no vlan tagging {0}'.format(vlan_id))
            elif t == 'untag':
                if vlan_id not in port['untagged_vlans'] or vlan_id != port['pvid_mode']:
                    cmds.append('vlan pvid {0}'.format(vlan_id))
                    cmds.append('vlan participation include {0}'.format(vlan_id))
            elif t == 'tag':
                if vlan_id not in port['tagged_vlans']:
                    cmds.append('vlan participation include {0}'.format(vlan_id))
                    cmds.append('vlan tagging {0}'.format(vlan_id))

    for i, cmds in sorted(interfaces_cmds.items()):
        if len(cmds) > 0:
            commands.append('interface {0}'.format(i))
            commands.extend(cmds)

    return commands


def parse_vlan_brief(vlan_out):
    have = []
    for line in vlan_out.split('\n'):
        obj = re.match(r'(?P<vlan_id>\d+)\s+(?P<name>[^\s]+)\s+', line)
        if obj:
            have.append(obj.groupdict())
    return have


def parse_interfaces_switchport(cmd_out):
    ports = dict()
    objs = re.findall(
        r'Port: (\d+\/\d+)\n'
        'VLAN Membership Mode:(.*)\n'
        'Access Mode VLAN:(.*)\n'
        'General Mode PVID:(.*)\n'
        'General Mode Ingress Filtering:(.*)\n'
        'General Mode Acceptable Frame Type:(.*)\n'
        'General Mode Dynamically Added VLANs:(.*)\n'
        'General Mode Untagged VLANs:(.*)\n'
        'General Mode Tagged VLANs:(.*)\n'
        'General Mode Forbidden VLANs:(.*)\n', cmd_out)
    for o in objs:
        port = {
            'interface': o[0],
            'pvid_mode': o[3].replace("(default)", "").strip(),
            'untagged_vlans': o[7].strip().split(','),
            'tagged_vlans': o[8].strip().split(','),
            'forbidden_vlans': o[9].strip().split(',')
        }
        ports[port['interface']] = port
    return ports


def map_ports_to_obj(module):
    return parse_interfaces_switchport(run_commands(module, ['show interfaces switchport'])[0])


def map_config_to_obj(module):
    return parse_vlan_brief(run_commands(module, ['show vlan brief'])[0])


def check_params(module, want):
    def check_parmams_interface(interfaces):
        if interfaces:
            for i in interfaces:
                match = re.search(r'(\d+)\/(\d+)-(\d+)\/(\d+)', i)
                if match:
                    if match.group(1) != match.group(3):
                        module.fail_json(msg="interface range must be withing same group: " + i)
                else:
                    match = re.search(r'(\d+)\/(\d+)', i)
                    if not match and i != 'all':
                        module.fail_json(msg="wrong interface format: " + i)

    for w in want:
        auto_tag = w['auto_tag']
        auto_untag = w['auto_untag']
        auto_exclude = w['auto_exclude']

        c = 0
        if auto_tag:
            c = c + 1

        if auto_untag:
            c = c + 1

        if auto_exclude:
            c = c + 1

        if c > 1:
            module.fail_json(msg="parameters are mutually exclusive: auto_tag, auto_untag, auto_exclude")
            return

        check_parmams_interface(w['tagged_interfaces'])
        check_parmams_interface(w['untagged_interfaces'])
        check_parmams_interface(w['excluded_interfaces'])


def main():
    """ main entry point for module execution
    """
    element_spec = dict(
        vlan_id=dict(type='int'),
        name=dict(),
        tagged_interfaces=dict(type='list'),
        untagged_interfaces=dict(type='list'),
        excluded_interfaces=dict(type='list'),
        auto_tag=dict(type='bool'),
        auto_exclude=dict(type='bool'),
        auto_untag=dict(type='bool'),
        state=dict(default='present',
                   choices=['present', 'absent'])
    )

    argument_spec = build_aggregate_spec(
        element_spec,
        ['vlan_id'],
        dict(purge=dict(default=False, type='bool'))
    )

    required_one_of = [['vlan_id', 'aggregate']]
    mutually_exclusive = [
        ['vlan_id', 'aggregate'],
        ['auto_tag', 'auto_untag', 'auto_exclude']]

    module = AnsibleModule(argument_spec=argument_spec,
                           required_one_of=required_one_of,
                           mutually_exclusive=mutually_exclusive,
                           supports_check_mode=True)
    result = {'changed': False}

    want = map_params_to_obj(module)
    have = map_config_to_obj(module)

    check_params(module, want)

    # vlans are not created/deleted in configure mode
    commands = map_vlans_to_commands((want, have), module)
    result['commands'] = commands

    if commands:
        if not module.check_mode:
            run_commands(module, commands, check_rc=False)
        result['changed'] = True

    ports = map_ports_to_obj(module)

    # interfaces vlan are set in configure mode
    commands = map_interfaces_to_commands(want, ports, module)
    if result['commands']:
        result['commands'].extend(commands)
    else:
        result['commands'] = commands

    if commands:
        if not module.check_mode:
            load_config(module, commands)
        result['changed'] = True

    module.exit_json(**result)


if __name__ == '__main__':
    main()
