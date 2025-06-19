# utils.py (심볼 테이블 채우는 역할에 집중하도록 재설계)
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


# --- Parso 기반 함수 (스코프 채우기용) ---

def _add_parso_target_names_to_scope(target_node: parso.tree.BaseNode, scope: Scope, symbol_type: SymbolType = SymbolType.VARIABLE):
    """Helper: Parso 할당/정의 대상 노드에서 변수 이름을 추출하여 주어진 스코프에 Symbol로 정의합니다."""
    node_type = target_node.type
    # 파라미터 노드(param) 자체를 처리
    if node_type == 'param':
        # param 노드의 첫 번째 자식(보통 name)에 대해 재귀 호출
        if hasattr(target_node, 'children') and len(target_node.children) > 0:
             _add_parso_target_names_to_scope(target_node.children[0], scope, symbol_type)
        return

    # 실제 이름(Leaf)을 찾았을 때
    if node_type == 'name':
        if isinstance(target_node, parso.tree.Leaf):
             scope.define(Symbol(target_node.value, symbol_type, target_node))
    # 튜플/리스트 언패킹 처리
    elif node_type in ('testlist_star_expr', 'exprlist', 'testlist', 'atom', 'tfpdef') and hasattr(target_node, 'children'):
        for child in target_node.children:
            # 재귀적으로 내부의 이름들을 찾아 스코프에 추가
            _add_parso_target_names_to_scope(child, scope, symbol_type)


def _populate_scope_from_node_recursive(node: parso.tree.BaseNode, current_scope: Scope):
    """
    주어진 Parso 노드와 그 하위를 재귀적으로 탐색하며 정의를 찾아 현재 스코프에 추가합니다.
    새로운 스코프(함수/클래스)를 만나면 재귀를 중단합니다.
    """
    node_type = node.type

    # 1. 새로운 스코프(함수/클래스) 정의 - 현재 스코프에 이름만 정의하고, 내부는 탐색하지 않음
    if node_type in ('funcdef', 'classdef'):
        name_node = node.children[1]
        if name_node.type == 'name' and isinstance(name_node, parso.tree.Leaf):
            symbol_type = SymbolType.FUNCTION if node_type == 'funcdef' else SymbolType.CLASS
            current_scope.define(Symbol(name_node.value, symbol_type, name_node))
        # 새로운 스코프가 시작되므로, 이 노드의 자식들은 여기서 더 이상 탐색하지 않음.
        # 스코프 트리를 만드는 Linter의 _build_and_visit_parso에서 처리할 것임.
        return # *** 재귀 중단 ***

    # 2. 다른 모든 정의 구문 처리
    # Import 문
    if node_type == 'simple_stmt' and len(node.children) > 0 and node.children[0].type in ('import_name', 'import_from'):
        import_stmt = node.children[0]
        try:
            for name_leaf in import_stmt.get_defined_names():
                if name_leaf.value != '*':
                    symbol_type = SymbolType.MODULE if import_stmt.type == 'import_name' else SymbolType.IMPORTED_NAME
                    current_scope.define(Symbol(name_leaf.value, symbol_type, name_leaf))
        except Exception as e: print(f"Error parsing import names: {e}", file=sys.stderr)
    # 일반/주석 할당문
    elif node_type == 'simple_stmt' and len(node.children) > 0 and node.children[0].type == 'expr_stmt':
        expr_stmt = node.children[0]
        if len(expr_stmt.children) >= 2 and expr_stmt.children[1].type == 'operator':
            if expr_stmt.children[1].value == '=' or expr_stmt.children[1].value == ':':
                _add_parso_target_names_to_scope(expr_stmt.children[0], current_scope)
    # For 루프 변수
    elif node_type == 'for_stmt':
        if len(node.children) >= 2: _add_parso_target_names_to_scope(node.children[1], current_scope)
    # With ... as 변수
    elif node_type == 'with_item':
        for i, item_child in enumerate(node.children):
            if isinstance(item_child, parso.tree.Leaf) and item_child.value == 'as':
                if i + 1 < len(node.children): _add_parso_target_names_to_scope(node.children[i+1], current_scope)
    # Except ... as 변수
    elif node_type == 'except_clause':
        as_found = False
        for child in node.children:
            if as_found and child.type == 'name':
                if isinstance(child, parso.tree.Leaf): current_scope.define(Symbol(child.value, SymbolType.VARIABLE, child)); break
            if isinstance(child, parso.tree.Leaf) and child.value == 'as': as_found = True
            elif as_found: as_found = False
    # Walrus 연산자
    elif node_type == 'namedexpr_test':
        if len(node.children) > 0 and node.children[0].type == 'name':
            if isinstance(node.children[0], parso.tree.Leaf):
                current_scope.define(Symbol(node.children[0].value, SymbolType.VARIABLE, node.children[0]))

    # 3. 다른 모든 자식 노드는 재귀적으로 하위 탐색
    if hasattr(node, 'children'):
        for child in node.children:
            _populate_scope_from_node_recursive(child, current_scope)


def populate_scope_from_parso(scope: Scope):
    """
    주어진 Parso 스코프 노드를 분석하여 심볼 테이블(Scope 객체)을 채웁니다.
    """
    scope_node = scope.node
    try:
        # 1. 함수/람다 매개변수 먼저 수집
        if isinstance(scope_node, (pt.Function, pt.Lambda)):
            for param in scope_node.get_params():
                _add_parso_target_names_to_scope(param, scope, SymbolType.PARAMETER)

        # 2. 현재 스코프의 본문(suite)에 있는 직계 자식 노드들 순회
        nodes_to_process = []
        if isinstance(scope_node, pt.Module):
            nodes_to_process = scope_node.children
        elif hasattr(scope_node, 'get_suite'): # Function, Class
             suite = scope_node.get_suite()
             if suite: nodes_to_process = suite.children

        for node in nodes_to_process:
            _populate_scope_from_node_recursive(node, scope)

    except Exception as e:
         scope_repr = repr(scope_node); print(f"Error in populate_scope_from_parso for {scope_repr[:100]}...: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr)

def check_module_exists(module_name: str) -> bool:
    if not module_name or module_name.startswith('.'): return True
    try:
        top_level_module = module_name.split('.')[0]
        return importlib.util.find_spec(top_level_module) is not None
    except Exception:
        return True

# --- Astroid 기반 함수 ---
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

def _populate_scope_from_parso_node(node: parso.tree.BaseNode, current_scope: Scope):
    """주어진 Parso 노드와 그 하위에서 정의를 찾아 현재 스코프에 추가합니다."""
    node_type = node.type

    # A. 새로운 스코프(함수/클래스)를 만나면, 이름만 정의하고 내부 탐색은 중단.
    #    (내부 탐색은 Linter의 메인 방문 로직에서 새로운 Scope 객체와 함께 시작됨)
    if node_type in ('funcdef', 'classdef'):
        name_node = node.children[1]
        if name_node.type == 'name' and isinstance(name_node, parso.tree.Leaf):
            symbol_type = SymbolType.FUNCTION if node_type == 'funcdef' else SymbolType.CLASS
            current_scope.define(Symbol(name_node.value, symbol_type, name_node))
        return # *** 재귀 중단 ***

    # B. 다른 모든 정의 구문 처리
    # Import 문
    if node_type == 'simple_stmt' and len(node.children) > 0 and node.children[0].type in ('import_name', 'import_from'):
        import_stmt = node.children[0]
        try:
            for name_leaf in import_stmt.get_defined_names():
                if name_leaf.value != '*':
                    symbol_type = SymbolType.MODULE if import_stmt.type == 'import_name' else SymbolType.IMPORTED_NAME
                    current_scope.define(Symbol(name_leaf.value, symbol_type, name_leaf))
        except Exception as e: print(f"Error parsing import names: {e}", file=sys.stderr)
    # 할당문
    elif node_type == 'simple_stmt' and len(node.children) > 0 and node.children[0].type == 'expr_stmt':
        expr_stmt = node.children[0]
        if len(expr_stmt.children) >= 2 and expr_stmt.children[1].type == 'operator':
            op_val = expr_stmt.children[1].value
            if op_val == '=' or op_val == ':':
                _add_parso_target_names_to_scope(expr_stmt.children[0], current_scope)
    # For 루프 변수
    elif node_type == 'for_stmt':
        if len(node.children) >= 2:
            _add_parso_target_names_to_scope(node.children[1], current_scope)
    # With ... as 변수
    elif node_type == 'with_item':
        for i, item_child in enumerate(node.children):
            if isinstance(item_child, parso.tree.Leaf) and item_child.value == 'as':
                if i + 1 < len(node.children):
                    _add_parso_target_names_to_scope(node.children[i+1], current_scope)
    # Except ... as 변수
    elif node_type == 'except_clause':
        as_found = False
        for child in node.children:
            if as_found and child.type == 'name':
                if isinstance(child, parso.tree.Leaf):
                    current_scope.define(Symbol(child.value, SymbolType.VARIABLE, child)); break
            if isinstance(child, parso.tree.Leaf) and child.value == 'as': as_found = True
            elif as_found: as_found = False
    # Walrus 연산자
    elif node_type == 'namedexpr_test':
        if len(node.children) > 0 and node.children[0].type == 'name':
            if isinstance(node.children[0], parso.tree.Leaf):
                current_scope.define(Symbol(node.children[0].value, SymbolType.VARIABLE, node.children[0]))

    # C. 자식 노드 재귀 탐색
    if hasattr(node, 'children'):
        for child in node.children:
            # funcdef/classdef는 위에서 이미 return 했으므로 여기서는 재귀 안 함.
            _populate_scope_from_parso_node(child, current_scope)