"""This script generates the XAP protocol generated source to be compiled into QMK.
"""
import re

from milc import cli
from qmk.path import normpath
from qmk.commands import get_git_version
from qmk.xap import latest_xap_defs
from qmk.constants import GPL2_HEADER_C_LIKE, GENERATED_HEADER_C_LIKE


def _append_defines(lines, route_container, name_stack=[]):
    name_stack.append(route_container['define'].upper())
    for route_id in route_container['routes']:
        route = route_container['routes'][route_id]
        name_stack.append(route['define'].upper())
        name_stack_str = ('_'.join(name_stack)).upper()
        if route['type'] == 'router':
            route_name = route['name']
            lines.append(f'//----------------------------------------------------------------')
            lines.append(f'// Subsystem: {route_name}')
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
        is_secure = 1 if ('secure' in child and child['secure'] is True) else 0

        # Generate the table entry
        if child['type'] == 'router':

            # If we're a router, we need to offload to the child table
            lines.append(f'    [{name_stack_str}] = {{ .flags = {{ .type = XAP_ROUTE, .is_secure = {is_secure} }}, .child_routes = {name_stack_str.lower()}_routes, .child_routes_len = sizeof({name_stack_str.lower()}_routes)/sizeof({name_stack_str.lower()}_routes[0]) }},')

        elif child['type'] == 'command':

            # If we're a command, we need to either return a constant, or execute a function
            if 'returns_constant' in child:
                # Auto-generated route handlers
                ret_define = child['returns_constant']
                lines.append(f'    [{name_stack_str}] = {{ .flags = {{ .type = XAP_VALUE, .is_secure = {is_secure} }}, .u32value = ({ret_define}) }},')

            elif 'returns_getter' in child and child['returns_getter'] is True:
                # Auto-generated route handlers
                lines.append(f'    [{name_stack_str}] = {{ .flags = {{ .type = XAP_GETTER, .is_secure = {is_secure} }}, .u32getter = &{name_stack_str.lower()}_getter }},')

            else:
                # External route handler
                lines.append(f'    [{name_stack_str}] = {{ .flags = {{ .type = XAP_EXECUTE, .is_secure = {is_secure} }}, .handler = &{name_stack_str.lower()}_handler }},')

        name_stack.pop()

    lines.append('};')

    # Compile-time validate that the array fits
    name_stack_str = ('_'.join(name_stack)).lower()
    lines.append(f'_Static_assert((sizeof({name_stack_str.lower()}_routes)/sizeof({name_stack_str.lower()}_routes[0])) <= 32, "Too many routes in {name_stack_str.lower()}_routes, should be max of 32");')
    lines.append('')
    name_stack.pop()


def _append_route_handler(lines, route, name):
    if route['return_type'].startswith('u32'):
        if 'returns_constant' in route:
            # Handled directly in the table
            pass
        elif 'returns_getter' in route and route['returns_getter'] is True:
            # Handled directly in the table
            pass
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
            elif 'returns_getter' in route and route['returns_getter'] is True:
                # External getter
                lines.append(f'extern uint32_t {name_stack_str.lower()}_getter(void);')
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

    lines = [GPL2_HEADER_C_LIKE, GENERATED_HEADER_C_LIKE]

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

    lines = [GPL2_HEADER_C_LIKE, GENERATED_HEADER_C_LIKE, '#pragma once','']

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
