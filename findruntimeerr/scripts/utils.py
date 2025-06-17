# utils.py (심볼 테이블 채우는 역할로 변경, 순환 참조 수정)
import astroid
import parso
from parso.python import tree as pt
import sys
from typing import Optional, Set, Union, List, Dict, Any, cast
import traceback
import importlib.util

# 새로 만든 symbol_table 모듈에서 클래스 import
from symbol_table import Symbol, Scope, SymbolType

# Astroid/Parso 스코프 타입 정의
AstroidScopeNode = Union[astroid.Module, astroid.FunctionDef, astroid.Lambda, astroid.ClassDef, astroid.GeneratorExp, astroid.ListComp, astroid.SetComp, astroid.DictComp]
ParsoScopeNode = Union[pt.Module, pt.Function, pt.Class, pt.Lambda]

# --- Parso 기반 함수 ---

def _add_parso_target_names_to_scope(target_node: parso.tree.BaseNode, scope: Scope, symbol_type: SymbolType = SymbolType.VARIABLE):
    """Helper: Parso 할당/정의 대상 노드에서 변수 이름을 추출하여 주어진 스코프에 Symbol로 정의합니다."""
    node_type = target_node.type
    if node_type == 'name':
        if isinstance(target_node, parso.tree.Leaf):
             scope.define(Symbol(target_node.value, symbol_type, target_node))
    elif node_type in ('testlist_star_expr', 'exprlist', 'testlist', 'atom', 'tfpdef') and hasattr(target_node, 'children'):
        for child in target_node.children:
            # 재귀적으로 내부의 이름들을 찾아 스코프에 추가
            _add_parso_target_names_to_scope(child, scope, symbol_type)


def _populate_scope_from_parso_node(node: parso.tree.BaseNode, current_scope: Scope):
    """주어진 Parso 노드를 분석하여 이름 정의를 찾아 현재 스코프에 추가하는 헬퍼 함수."""
    node_type = node.type

    # A. 함수 정의
    if node_type == 'funcdef':
        name_node = node.children[1]
        if name_node.type == 'name' and isinstance(name_node, parso.tree.Leaf):
            current_scope.define(Symbol(name_node.value, SymbolType.FUNCTION, name_node))
    # B. 클래스 정의
    elif node_type == 'classdef':
        name_node = node.children[1]
        if name_node.type == 'name' and isinstance(name_node, parso.tree.Leaf):
            current_scope.define(Symbol(name_node.value, SymbolType.CLASS, name_node))
    # C. Import 문
    elif node_type == 'simple_stmt' and len(node.children) > 0 and node.children[0].type in ('import_name', 'import_from'):
        import_stmt = node.children[0]
        try:
            for name_leaf in import_stmt.get_defined_names():
                if name_leaf.value != '*':
                    symbol_type = SymbolType.MODULE if import_stmt.type == 'import_name' else SymbolType.IMPORTED_NAME
                    current_scope.define(Symbol(name_leaf.value, symbol_type, name_leaf))
        except Exception as e: print(f"Error parsing import names: {e}", file=sys.stderr)
    # D. 일반/주석 할당문 (var = value / var: type = value)
    elif node_type == 'simple_stmt' and len(node.children) > 0 and node.children[0].type == 'expr_stmt':
        expr_stmt = node.children[0]
        if len(expr_stmt.children) >= 2 and expr_stmt.children[1].type == 'operator':
            op_val = expr_stmt.children[1].value
            if op_val == '=' or op_val == ':':
                _add_parso_target_names_to_scope(expr_stmt.children[0], current_scope)
    # E. For 루프 변수
    elif node_type == 'for_stmt':
        if len(node.children) >= 2: _add_parso_target_names_to_scope(node.children[1], current_scope)
    # F. With/as, Except/as, Walrus 등 복합문 내부
    if hasattr(node, 'iter_preorder'):
        for sub_node in node.iter_preorder():
            sub_node_type = sub_node.type
            if sub_node_type == 'with_item':
                for i, item_child in enumerate(sub_node.children):
                     if isinstance(item_child, parso.tree.Leaf) and item_child.value == 'as':
                          if i + 1 < len(sub_node.children): _add_parso_target_names_to_scope(sub_node.children[i+1], current_scope); break
            elif sub_node_type == 'except_clause':
                as_found = False
                for except_child in sub_node.children:
                     if as_found and except_child.type == 'name':
                          if isinstance(except_child, parso.tree.Leaf): current_scope.define(Symbol(except_child.value, SymbolType.VARIABLE, except_child)); break
                     if isinstance(except_child, parso.tree.Leaf) and except_child.value == 'as': as_found = True
                     elif as_found: as_found = False
            elif sub_node_type == 'namedexpr_test': # Walrus operator
                 if len(sub_node.children) > 0 and sub_node.children[0].type == 'name':
                      name_leaf = sub_node.children[0]
                      if isinstance(name_leaf, parso.tree.Leaf):
                           current_scope.define(Symbol(name_leaf.value, SymbolType.VARIABLE, name_leaf))


def populate_scope_from_parso(scope: Scope):
    """
    주어진 Parso 스코프 노드를 분석하여 심볼 테이블(Scope 객체)을 채웁니다.
    """
    scope_node = scope.node
    try:
        # 1. 함수/람다 매개변수
        if isinstance(scope_node, (pt.Function, pt.Lambda)):
            for param in scope_node.get_params():
                _add_parso_target_names_to_scope(param, scope, SymbolType.PARAMETER)

        # 2. 클래스 내부 정의 (메서드, 클래스 변수)
        if isinstance(scope_node, pt.Class):
             class_suite = scope_node.get_suite()
             if class_suite:
                 for node_in_class in class_suite.children:
                     _populate_scope_from_parso_node(node_in_class, scope)

        # 3. 현재 스코프의 본문에 있는 직계 자식 노드들 순회
        nodes_to_check = []
        if isinstance(scope_node, pt.Module):
            nodes_to_check = scope_node.children
        elif hasattr(scope_node, 'get_suite'): # Function, Class
             suite = scope_node.get_suite()
             if suite: nodes_to_check = suite.children

        for node in nodes_to_check:
            _populate_scope_from_parso_node(node, scope)

    except Exception as e:
         scope_repr = repr(scope_node); print(f"Error in populate_scope_from_parso for {scope_repr[:100]}...: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr)


def check_module_exists(module_name: str) -> bool:
    if not module_name or module_name.startswith('.'): return True
    try:
        top_level_module = module_name.split('.')[0]
        return importlib.util.find_spec(top_level_module) is not None
    except Exception:
        return True

# --- Astroid 기반 함수 (Static 체커들이 사용) ---
def get_type_astroid(node: astroid.NodeNG) -> Optional[str]:
    try:
        inferred_list = list(node.infer(context=None));
        if not inferred_list or inferred_list[0] is astroid.Uninferable:
            if isinstance(node, astroid.Const): return type(node.value).__name__
            elif isinstance(node, astroid.List): return 'list'
            elif isinstance(node, astroid.Tuple): return 'tuple'
            elif isinstance(node, astroid.Dict): return 'dict'
            elif isinstance(node, astroid.Set): return 'set'
            elif isinstance(node, astroid.Lambda): return 'function'
            elif isinstance(node, astroid.FunctionDef): return 'function'
            elif isinstance(node, astroid.ClassDef): return 'type'
            return None
        primary_type = inferred_list[0]
        if isinstance(primary_type, astroid.Instance):
            proxied = getattr(primary_type, '_proxied', primary_type)
            return getattr(proxied, 'qname', getattr(proxied, 'name', type(proxied).__name__))
        elif isinstance(primary_type, astroid.ClassDef):
             return getattr(primary_type, 'qname', primary_type.name)
        elif isinstance(primary_type, astroid.FunctionDef):
            return getattr(primary_type, 'qname', 'function')
        elif isinstance(primary_type, astroid.Const):
             return type(primary_type.value).__name__
        return getattr(primary_type, 'qname', getattr(primary_type, 'name', type(primary_type).__name__))
    except astroid.InferenceError: return None
    except Exception as e: node_repr = repr(node); print(f"Error in get_type_astroid for {node_repr[:100]}...: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr); return None

def is_compatible_astroid(type1_fq: Optional[str], type2_fq: Optional[str], op: str) -> bool:
    if type1_fq is None or type2_fq is None: return True
    type1 = type1_fq.split('.')[-1].lower()
    type2 = type2_fq.split('.')[-1].lower()
    numeric_types = ("int", "float", "complex", "bool")
    sequence_types = ("str", "list", "tuple", "bytes", "bytearray", "range")
    set_types = ("set", "frozenset")
    mapping_types = ("dict",)
    if type1 in numeric_types and type2 in numeric_types:
        if op in ("+", "-", "*", "/", "//", "%", "**", "<", "<=", ">", ">=", "==", "!="):
            if "complex" in (type1, type2) and op in ("<", "<=", ">", ">="): return False
            return True
        if type1 in ("int", "bool") and type2 in ("int", "bool") and op in ("&", "|", "^", "<<", ">>", "~"): return True
    if type1 in sequence_types and type2 in sequence_types:
        if type1 == type2 and op == '+': return True
        if type1 in ("str", "tuple", "list", "bytes", "bytearray") and type1 == type2 and op in ("==", "!=", "<", "<=", ">", ">="): return True
    if op == '*' and ((type1 in sequence_types and type2 == 'int') or (type1 == 'int' and type2 in sequence_types)): return True
    if op == '%' and type1 == "str": return True
    if type1 in set_types and type2 in set_types and op in ("|", "&", "-", "^", "<=", "<", ">=", ">", "==", "!="): return True
    if op in ("in", "not in") and (type2 in sequence_types or type2 in set_types or type2 in mapping_types): return True
    if op in ('and', 'or'): return True
    if op == 'not': return True
    if op in ('+', '-') and type1 in numeric_types: return True
    return False

def collect_defined_variables_astroid(scope_node: AstroidScopeNode) -> Set[str]:
     defined_vars: Set[str] = set()
     try:
        if isinstance(scope_node, (astroid.FunctionDef, astroid.Lambda)): defined_vars.update(scope_node.argnames())
        assign_targets = [t.name for an in scope_node.nodes_of_class((astroid.Assign, astroid.AugAssign, astroid.AnnAssign)) for t in an.targets if isinstance(t, astroid.AssignName)]
        defined_vars.update(assign_targets)
        unpacking_targets = [e.name for an in scope_node.nodes_of_class((astroid.Assign, astroid.AnnAssign)) for t in an.targets if isinstance(t, (astroid.Tuple, astroid.List)) for e in t.elts if isinstance(e, astroid.AssignName)]
        defined_vars.update(unpacking_targets)
        import_names = set()
        for imp_node in scope_node.nodes_of_class((astroid.Import, astroid.ImportFrom)):
            for name, alias in imp_node.names:
                if name != '*': import_names.add(alias or name.split('.')[0] if isinstance(imp_node, astroid.Import) else alias or name)
        defined_vars.update(import_names)
        for_targets = [t.name for fn in scope_node.nodes_of_class(astroid.For) for t in [fn.target] if isinstance(t, astroid.AssignName)]
        defined_vars.update(for_targets)
        for_unpack_targets = [e.name for fn in scope_node.nodes_of_class(astroid.For) for t in [fn.target] if isinstance(t, (astroid.Tuple, astroid.List)) for e in t.elts if isinstance(e, astroid.AssignName)]
        defined_vars.update(for_unpack_targets)
        with_targets = [t.name for wn in scope_node.nodes_of_class(astroid.With) for _, ats in wn.items if ats for t in ([ats] if isinstance(ats, astroid.AssignName) else ats.elts if isinstance(ats, (astroid.Tuple, astroid.List)) else []) if isinstance(t, astroid.AssignName)]
        defined_vars.update(with_targets)
        def_names = [dn.name for dn in scope_node.nodes_of_class((astroid.FunctionDef, astroid.ClassDef)) if dn.parent is scope_node]
        defined_vars.update(def_names)
        except_names = [en.name.name for en in scope_node.nodes_of_class(astroid.ExceptHandler) if en.name and isinstance(en.name, astroid.AssignName)]
        defined_vars.update(except_names)
     except Exception as e:
         scope_name = getattr(scope_node, 'name', type(scope_node).__name__); print(f"Error collecting astroid vars in '{scope_name}': {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr)
     return defined_vars