# scripts/utils.py
import astroid
import parso
from parso.python import tree as pt
import sys
from typing import Optional, Set, Union, List, Dict, Any, cast
import traceback
import importlib.util # <--- 추가

# symbol_table.py에서 클래스 import
from symbol_table import Symbol, Scope, SymbolType

# 타입 정의
AstroidScopeNode = Union[astroid.Module, astroid.FunctionDef, astroid.Lambda, astroid.ClassDef, astroid.GeneratorExp, astroid.ListComp, astroid.SetComp, astroid.DictComp]
ParsoScopeNode = Union[pt.Module, pt.Function, pt.Class, pt.Lambda]

# --- Parso 기반 함수 (스코프 채우기용) ---

def _add_parso_target_names_to_scope(target_node: parso.tree.BaseNode, scope: Scope, symbol_type: SymbolType = SymbolType.VARIABLE):
    """Helper: Parso 할당/정의 대상 노드에서 변수 이름을 추출하여 주어진 스코프에 Symbol로 정의합니다."""
    node_type = target_node.type
    if node_type == 'param':
        if hasattr(target_node, 'children') and len(target_node.children) > 0:
             _add_parso_target_names_to_scope(target_node.children[0], scope, symbol_type)
        return
    if node_type == 'name':
        if isinstance(target_node, parso.tree.Leaf):
             scope.define(Symbol(target_node.value, symbol_type, target_node))
    elif node_type in ('testlist_star_expr', 'exprlist', 'testlist', 'atom', 'tfpdef') and hasattr(target_node, 'children'):
        for child in target_node.children:
            _add_parso_target_names_to_scope(child, scope, symbol_type)


def _populate_scope_from_node_recursive(node: parso.tree.BaseNode, current_scope: Scope):
    """
    주어진 Parso 노드와 그 하위를 재귀적으로 탐색하며 정의를 찾아 현재 스코프에 추가합니다.
    새로운 스코프(함수/클래스)를 만나면 재귀를 중단합니다.
    """
    node_type = node.type

    if node_type in ('funcdef', 'classdef'):
        name_node = node.children[1]
        if name_node.type == 'name' and isinstance(name_node, parso.tree.Leaf):
            symbol_type = SymbolType.FUNCTION if node_type == 'funcdef' else SymbolType.CLASS
            current_scope.define(Symbol(name_node.value, symbol_type, name_node))
        return

    if node_type == 'simple_stmt' and len(node.children) > 0 and node.children[0].type in ('import_name', 'import_from'):
        import_stmt = node.children[0]
        
        # 'from a.b.c import ...' 구문에서 'a'를 심볼로 등록하는 안정적인 로직
        if import_stmt.type == 'import_from':
            module_name_node = next((c for c in import_stmt.children if c.type in ('dotted_name', 'name')), None)
            if module_name_node:
                first_part_name_node = module_name_node.children[0] if hasattr(module_name_node, 'children') else module_name_node
                if first_part_name_node.type == 'name' and isinstance(first_part_name_node, parso.tree.Leaf):
                    current_scope.define(Symbol(first_part_name_node.value, SymbolType.MODULE, first_part_name_node))

        try:
            for name_leaf in import_stmt.get_defined_names():
                if name_leaf.value != '*':
                    symbol_type = SymbolType.MODULE if import_stmt.type == 'import_name' else SymbolType.IMPORTED_NAME
                    current_scope.define(Symbol(name_leaf.value, symbol_type, name_leaf))
        except Exception:
            pass
            
    elif node_type == 'simple_stmt' and len(node.children) > 0 and node.children[0].type == 'expr_stmt':
        expr_stmt = node.children[0]
        if len(expr_stmt.children) >= 2 and expr_stmt.children[1].type == 'operator' and expr_stmt.children[1].value in ('=', ':'):
            _add_parso_target_names_to_scope(expr_stmt.children[0], current_scope)
    elif node_type == 'for_stmt':
        if len(node.children) >= 2: _add_parso_target_names_to_scope(node.children[1], current_scope)
    elif node_type == 'with_item':
        as_node = next((c for c in node.children if isinstance(c, parso.tree.Leaf) and c.value == 'as'), None)
        if as_node and as_node.get_next_sibling():
            _add_parso_target_names_to_scope(as_node.get_next_sibling(), current_scope)
    elif node_type == 'except_clause':
        as_node = next((c for c in node.children if isinstance(c, parso.tree.Leaf) and c.value == 'as'), None)
        if as_node and as_node.get_next_sibling() and as_node.get_next_sibling().type == 'name':
            name_leaf = as_node.get_next_sibling()
            current_scope.define(Symbol(name_leaf.value, SymbolType.VARIABLE, name_leaf))
    elif node_type == 'namedexpr_test':
        if len(node.children) > 0 and node.children[0].type == 'name' and isinstance(node.children[0], parso.tree.Leaf):
            current_scope.define(Symbol(node.children[0].value, SymbolType.VARIABLE, node.children[0]))

    if hasattr(node, 'children'):
        for child in node.children:
            _populate_scope_from_node_recursive(child, current_scope)


def populate_scope_from_parso(scope: Scope):
    scope_node = scope.node
    try:
        if isinstance(scope_node, (pt.Function, pt.Lambda)):
            for param in scope_node.get_params():
                _add_parso_target_names_to_scope(param, scope, SymbolType.PARAMETER)
        nodes_to_process = []
        if isinstance(scope_node, pt.Module):
            nodes_to_process = scope_node.children
        elif hasattr(scope_node, 'get_suite'):
             suite = scope_node.get_suite()
             if suite: nodes_to_process = suite.children
        for node in nodes_to_process:
            _populate_scope_from_node_recursive(node, scope)
    except Exception:
         pass

# --- 이 함수를 파일 끝에 추가 ---
def check_module_exists(module_name: str) -> bool:
    """주어진 이름의 모듈이 현재 환경에 설치되어 있는지 확인합니다."""
    if not module_name or module_name.startswith('.'):
        return True
    try:
        top_level_module = module_name.split('.')[0]
        return importlib.util.find_spec(top_level_module) is not None
    except Exception:
        return True

# --- Astroid 기반 함수 (변경 없음) ---
def get_type_astroid(node: astroid.NodeNG) -> Optional[str]:
    # ... (이전과 동일)
    try:
        inferred_list = list(node.infer(context=None))
        if not inferred_list or inferred_list[0] is astroid.Uninferable:
            if isinstance(node, astroid.Const): return type(node.value).__name__
            return None
        primary_type = inferred_list[0]
        if hasattr(primary_type, 'pytype'):
            try: return primary_type.pytype()
            except Exception: pass
        if hasattr(primary_type, 'qname') and isinstance(primary_type.qname, str):
            return primary_type.qname
        if hasattr(primary_type, 'name') and isinstance(primary_type.name, str):
            return primary_type.name
        if isinstance(primary_type, astroid.Const):
            return type(primary_type.value).__name__
        return primary_type.__class__.__name__
    except (astroid.InferenceError, Exception):
        return None

def is_compatible_astroid(type1_fq: Optional[str], type2_fq: Optional[str], op: str) -> bool:
    # ... (이전과 동일)
    if type1_fq is None or type2_fq is None: return True
    type1, type2 = type1_fq.split('.')[-1].lower(), type2_fq.split('.')[-1].lower()
    numeric, sequence = ("int", "float", "complex", "bool"), ("str", "list", "tuple", "bytes", "bytearray", "range")
    if type1 in numeric and type2 in numeric: return True
    if op == '+' and type1 in sequence and type2 in sequence and type1 == type2: return True
    return False