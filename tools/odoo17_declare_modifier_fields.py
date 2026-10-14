"""Odoo 17: mọi trường dùng trong invisible/readonly/required/column_invisible phải có trong view.

Script thêm <field name="x" invisible="1"/> (hoặc column_invisible trong list) vào đúng phạm vi
(form / tree con / khối xpath) khi trường đó chưa được khai báo. Chạy lại nhiều lần không sinh trùng.
"""
import ast
import sys
from pathlib import Path

from lxml import etree

MODIFIERS = ('invisible', 'readonly', 'required', 'column_invisible')
IGNORED = {'parent', 'context', 'uid', 'True', 'False', 'None', 'id', 'today', 'datetime', 'context_today'}
SCOPES = ('form', 'tree', 'xpath', 'data')


def names_in(expr):
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError:
        return set()
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} - IGNORED


def scope_of(node):
    parent = node.getparent()
    while parent is not None and parent.tag not in SCOPES:
        parent = parent.getparent()
    return parent


def declared(scope):
    result = set()
    for field in scope.iter('field'):
        if scope_of(field) is scope or scope.tag in ('xpath', 'data'):
            result.add(field.get('name'))
    return result


def process(path):
    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(str(path), parser)
    changed = False
    for arch in tree.iter('field'):
        if arch.get('name') != 'arch' or arch.get('type') != 'xml':
            continue
        needed = {}
        for node in arch.iter():
            if not isinstance(node.tag, str) or node.tag == 'kanban':
                continue
            for attr in MODIFIERS:
                if node.get(attr):
                    scope = scope_of(node)
                    if scope is None or scope.tag == 'kanban':
                        continue
                    if any(anc.tag == 'kanban' for anc in node.iterancestors()):
                        continue
                    needed.setdefault(scope, set()).update(names_in(node.get(attr)))
        for scope, names in needed.items():
            missing = sorted(names - declared(scope))
            if scope.tag == 'xpath' and scope.get('position') == 'attributes':
                continue
            for name in missing:
                field = etree.Element('field', name=name)
                field.set('column_invisible' if scope.tag == 'tree' else 'invisible', '1')
                field.tail = scope.text
                insert_at = 0
                if scope.tag == 'form':
                    sheet = scope.find('sheet')
                    if sheet is not None:
                        scope, insert_at = sheet, 0
                        field.tail = sheet.text
                scope.insert(insert_at, field)
                changed = True
    if changed:
        tree.write(str(path), encoding='utf-8', xml_declaration=True)
        print('updated', path)


if __name__ == '__main__':
    for root in sys.argv[1:]:
        for path in Path(root).rglob('*.xml'):
            if '/views/' in str(path) or '/wizard/' in str(path):
                process(path)
