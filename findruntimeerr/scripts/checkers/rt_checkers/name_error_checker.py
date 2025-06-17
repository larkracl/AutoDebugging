import parso
from parso.python import tree as pt
import builtins
import sys
from typing import Optional, Tuple
from ..base_checkers import BaseParsoChecker

class RTNameErrorParsoChecker(BaseParsoChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'rt-name-error-parso'; node_types = ('name',)
    MSGS = {'0101': ("Potential NameError: Name '%s' might not be defined (RT-Parso)", 'undefined-variable-rt-parso', '')}

    def _is_attribute_name(self, node: parso.tree.Leaf) -> bool:
        parent = node.parent
        if parent and parent.type == 'trailer' and len(parent.children) == 2 and \
           parent.children[0].type == 'operator' and parent.children[0].value == '.' and \
           parent.children[1] is node:
            return True
        return False

    def _is_keyword_arg_name(self, node: parso.tree.Leaf) -> bool:
        parent = node.parent
        if parent and parent.type == 'argument' and len(parent.children) >= 2 and \
           parent.children[0] is node and parent.children[1].type == 'operator' and \
           parent.children[1].value == '=':
            return True
        return False

    def _is_definition_context(self, node: parso.tree.Leaf) -> bool:
        parent = node.parent
        if not parent: return False
        if parent.type in ('funcdef', 'classdef') and len(parent.children) > 1 and parent.children[1] is node:
            return True
        if parent.type == 'param' and hasattr(parent, 'name') and parent.name is node:
            return True
        return False

    def check(self, node: parso.tree.Leaf):
        node_value = node.value
        # 1. 빠른 제외 조건
        if hasattr(builtins, node_value): return
        if self._is_attribute_name(node): return
        if self._is_keyword_arg_name(node): return
        if self._is_definition_context(node): return
        try:
            definitions = list(node.infer())
            if not definitions:
                current_scope = self.linter.get_scope_for_node(node)
                if current_scope and current_scope.lookup(node.value, search_parents=False) is None:
                    self.add_message(node, '0101', (node_value,))
        except Exception as e:
            current_scope = self.linter.get_scope_for_node(node)
            if current_scope and current_scope.lookup(node.value) is None:
                self.add_message(node, '0101', (node_value,))
