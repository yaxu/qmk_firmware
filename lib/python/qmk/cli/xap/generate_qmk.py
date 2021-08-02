"""This script generates the XAP protocol generated source to be compiled into QMK.
"""
import hjson
import datetime
import re

from milc import cli
from qmk.path import normpath
from qmk.commands import get_git_version
from qmk.xap import latest_xap_defs


this_year = datetime.date.today().year
gpl_header = f'''\
/* Copyright {this_year} QMK
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */
'''

generated = '''\
/*******************************************************************************

88888888888 888      d8b                .d888 d8b 888               d8b
    888     888      Y8P               d88P"  Y8P 888               Y8P
    888     888                        888        888
    888     88888b.  888 .d8888b       888888 888 888  .d88b.       888 .d8888b
    888     888 "88b 888 88K           888    888 888 d8P  Y8b      888 88K
    888     888  888 888 "Y8888b.      888    888 888 88888888      888 "Y8888b.
    888     888  888 888      X88      888    888 888 Y8b.          888      X88
    888     888  888 888  88888P'      888    888 888  "Y8888       888  88888P'

                                                      888                 888
                                                      888                 888
                                                      888                 888
   .d88b.   .d88b.  88888b.   .d88b.  888d888 8888b.  888888 .d88b.   .d88888
  d88P"88b d8P  Y8b 888 "88b d8P  Y8b 888P"      "88b 888   d8P  Y8b d88" 888
  888  888 88888888 888  888 88888888 888    .d888888 888   88888888 888  888
  Y88b 888 Y8b.     888  888 Y8b.     888    888  888 Y88b. Y8b.     Y88b 888
   "Y88888  "Y8888  888  888  "Y8888  888    "Y888888  "Y888 "Y8888   "Y88888
       888
  Y8b d88P
   "Y88P"

*******************************************************************************/
'''


def _append_defines(lines, route_container, name_stack=[]):
    name_stack.append(route_container['define'].upper())
    for route_id in route_container['routes']:
        route = route_container['routes'][route_id]
        name_stack.append(route['define'].upper())
        name_stack_str = ('_'.join(name_stack)).upper()
        if route['type'] == 'router':
            lines.append(f'#define {name_stack_str} {route_id}')
            lines.append('')
            _append_defines(lines, route, name_stack[:-1])
            lines.append('')
        elif route['type'] == 'command':
            lines.append(f'#define {name_stack_str} {route_id}')
        name_stack.pop()
    name_stack.pop()


def _append_routing_table(lines, route, name_stack=[]):
    name_stack.append(route['define'].upper())
    name_stack_str = ('_'.join(name_stack)).lower()
    lines.append(f'static const xap_route_t {name_stack_str}_routes[] = {{')
    for child_id in route['routes']:
        child = route['routes'][child_id]
        name_stack.append(child['define'].upper())
        name_stack_str = ('_'.join(name_stack)).upper()
        is_secure = 1 if ('secure' in child and child['secure'] == 'true') else 0
        if child['type'] == 'router':
            lines.append(f'    [{name_stack_str}] = {{ .flags = {{ .type = XAP_ROUTE, .is_secure = {is_secure} }}, .child_routes = {name_stack_str.lower()}_routes, .child_routes_len = sizeof({name_stack_str.lower()}_routes)/sizeof({name_stack_str.lower()}_routes[0]) }},')
        elif child['type'] == 'command':
            if 'returns_constant' in child:
                # Auto-generated route handlers
                ret_define = child['returns_constant']
                lines.append(f'    [{name_stack_str}] = {{ .flags = {{ .type = XAP_VALUE_U32, .is_secure = {is_secure} }}, .u32value = ({ret_define}) }},')
            else:
                # External route handler
                lines.append(f'    [{name_stack_str}] = {{ .flags = {{ .type = XAP_EXECUTE, .is_secure = {is_secure} }}, .handler = &{name_stack_str.lower()}_handler }},')
        name_stack.pop()
    lines.append('};')
    lines.append('')
    name_stack.pop()


def _append_route_handler(lines, route, name):
    if route['return_type'].startswith('u32'):
        if 'returns_constant' in route:
            # Handled directly in the table
            pass
        elif 'returns_function' in route:
            ret_define = route['returns_function']
            lines.append(f'static bool {name}_handler(xap_token_t token, const uint8_t *data, size_t data_len) {{')
            lines.append(f'    return xap_respond_u32_handler(token, ({ret_define}));')
            lines.append(f'}}')
    else:
        # External route handler
        lines.append(f'extern bool {name_stack_str.lower()}_handler(xap_token_t token, const uint8_t *data, size_t data_len);')


def _append_routing_tables(lines, route_container, name_stack=[]):
    name_stack.append(route_container['define'].upper())
    for route_id in route_container['routes']:
        route = route_container['routes'][route_id]
        name_stack.append(route['define'].upper())
        name_stack_str = ('_'.join(name_stack)).upper()
        if route['type'] == 'router':
            _append_routing_tables(lines, route, name_stack[:-1])
            lines.append('')
        elif route['type'] == 'command':
            if 'returns_constant' in route:
                # Auto-generated route handlers
                _append_route_handler(lines, route, name_stack_str.lower())
            else:
                # External route handler
                lines.append(f'extern bool {name_stack_str.lower()}_handler(xap_token_t token, const uint8_t *data, size_t data_len);')
            lines.append('')
        name_stack.pop()
    name_stack.pop()
    _append_routing_table(lines, route_container, name_stack)


@cli.argument('-o', '--output', arg_only=True, type=normpath, help='File to write to')
@cli.subcommand('Generates the XAP protocol include.')
def xap_generate_qmk_inc(cli):
    """Generates the XAP protocol inline codegen file, generated during normal build.
    """
    xap_defs = latest_xap_defs()

    lines = [gpl_header, generated]

    # Append the routing tables
    _append_routing_tables(lines, xap_defs)

    xap_generated_inl = '\n'.join(lines)

    if cli.args.output:
        if cli.args.output.name == '-':
            print(xap_generated_inl)
        else:
            cli.args.output.parent.mkdir(parents=True, exist_ok=True)
            if cli.args.output.exists():
                cli.args.output.replace(cli.args.output.parent / (cli.args.output.name + '.bak'))
            cli.args.output.write_text(xap_generated_inl)


@cli.argument('-o', '--output', arg_only=True, type=normpath, help='File to write to')
@cli.subcommand('Generates the XAP protocol include.')
def xap_generate_qmk_h(cli):
    """Generates the XAP protocol header file, generated during normal build.
    """
    xap_defs = latest_xap_defs()

    lines = [gpl_header, generated, '#pragma once','']

    prog = re.compile(r'^(\d+)\.(\d+)\.(\d+)')
    b = prog.match(xap_defs['version'])
    lines.append(f'#define XAP_BCD_VERSION 0x{int(b.group(1)):02d}{int(b.group(2)):02d}{int(b.group(3)):04d}')
    b = prog.match(get_git_version())
    lines.append(f'#define QMK_BCD_VERSION 0x{int(b.group(1)):02d}{int(b.group(2)):02d}{int(b.group(3)):04d}')
    lines.append('')

    # Append the route and command defines
    _append_defines(lines, xap_defs)

    xap_generated_inl = '\n'.join(lines)

    if cli.args.output:
        if cli.args.output.name == '-':
            print(xap_generated_inl)
        else:
            cli.args.output.parent.mkdir(parents=True, exist_ok=True)
            if cli.args.output.exists():
                cli.args.output.replace(cli.args.output.parent / (cli.args.output.name + '.bak'))
            cli.args.output.write_text(xap_generated_inl)
