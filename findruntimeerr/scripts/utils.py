# utils.py (Parso 스코프 + Astroid 타입 함수, except 절 처리 수정)
import astroid
import parso
from parso.python import tree as pt # Parso 트리 타입
import sys
from typing import Optional, Set, Union, List, Dict, Any, cast # cast 추가
import traceback # traceback 추가

# Astroid 스코프 노드 타입들을 import
from astroid.nodes import Module as AstroidModule, FunctionDef as AstroidFunctionDef, Lambda as AstroidLambda, \
    ClassDef as AstroidClassDef, GeneratorExp as AstroidGeneratorExp, ListComp as AstroidListComp, \
    SetComp as AstroidSetComp, DictComp as AstroidDictComp

# Astroid 스코프 노드 타입을 위한 Union 타입 정의
AstroidScopeNode = Union[AstroidModule, AstroidFunctionDef, AstroidLambda, AstroidClassDef, AstroidGeneratorExp, AstroidListComp, AstroidSetComp, AstroidDictComp]

# Parso 스코프 노드 타입을 위한 Union 타입 정의
ParsoScopeNode = Union[pt.Module, pt.Function, pt.Class, pt.Lambda]


# --- Parso 기반 함수 ---

def _add_parso_target_names(target_node: parso.tree.BaseNode, defined_vars: Set[str]):
    """Helper: Parso 할당/정의 대상 노드에서 변수 이름을 추출하여 defined_vars에 추가합니다."""
    node_type = target_node.type
    if node_type == 'name': # 단순 이름 (a = 1, def a():, class a:, for a in)
        if isinstance(target_node, parso.tree.Leaf):
             defined_vars.add(target_node.value)
    # 튜플/리스트 언패킹 할당 (a, b = value / for a, b in iterable)
    # Common parent types for unpacking targets: testlist_star_expr, exprlist, testlist
    elif node_type in ('testlist_star_expr', 'exprlist', 'testlist', 'atom') and hasattr(target_node, 'children'):
        for child in target_node.children:
            # 재귀 호출로 내부 이름 노드 찾기 (쉼표, 괄호 등은 제외)
            if child.type == 'name' and isinstance(child, parso.tree.Leaf):
                defined_vars.add(child.value)
            # 리프가 아니면서 children이 있고, 단순 토큰이 아닌 경우만 재귀
            elif not isinstance(child, parso.tree.Leaf) and hasattr(child, 'children') and \
                 child.type not in ('operator', 'keyword') and \
                 (not hasattr(child, 'value') or child.value not in [',', '(', ')', '[', ']', '{', '}', ':']):
                 _add_parso_target_names(child, defined_vars)

def collect_defined_variables_parso(scope_node: ParsoScopeNode) -> Set[str]:
    """주어진 parso 스코프 노드 내에서 정의된 변수 이름을 수집합니다."""
    defined_vars: Set[str] = set()
    try:
        # 1. 함수/람다 매개변수
        if isinstance(scope_node, (pt.Function, pt.Lambda)):
            for param in scope_node.get_params():
                # param.name 은 이름(Leaf) 또는 튜플/리스트(Node)일 수 있음
                _add_parso_target_names(param.name, defined_vars)

        # 2. 클래스 내부의 정의 (메서드, 클래스 변수 - 클래스 스코프용)
        if isinstance(scope_node, pt.Class):
             class_suite = scope_node.get_suite()
             if class_suite:
                 for node_in_class in class_suite.children:
                      # 메서드 정의
                      if node_in_class.type == 'funcdef':
                           name_node = node_in_class.children[1] # 'def' name '('
                           if name_node.type == 'name' and isinstance(name_node, parso.tree.Leaf):
                                defined_vars.add(name_node.value)
                      # 클래스 변수 할당 (단순 할당: var = value)
                      elif node_in_class.type == 'simple_stmt' and len(node_in_class.children) > 0 and \
                           node_in_class.children[0].type == 'expr_stmt':
                           assign_expr = node_in_class.children[0]
                           if len(assign_expr.children) >= 3 and assign_expr.children[1].type == 'operator' and \
                              assign_expr.children[1].value == '=':
                                _add_parso_target_names(assign_expr.children[0], defined_vars)
                      # TODO: AnnAssign, AugAssign 등 클래스 내 다른 형태의 정의

        # 3. 현재 스코프의 직계 자식 노드들 순회 (Module, Function/Lambda body, Class suite)
        nodes_to_check = []
        if isinstance(scope_node, pt.Module): nodes_to_check = scope_node.children
        elif hasattr(scope_node, 'get_suite'): # Function, Class 의 suite
             suite = scope_node.get_suite()
             if suite: nodes_to_check = suite.children
        elif isinstance(scope_node, pt.Lambda) and len(scope_node.children) > 1 : # Lambda: ':' expression
             lambda_body_expr = scope_node.children[-1]
             # Lambda body is an expression, so direct assignments are rare (except walrus)
             # For walrus operator (:=) in lambda body:
             if lambda_body_expr.type == 'test': # test ( AnnAssign | test ... )
                  current_node_for_walrus = lambda_body_expr
                  if hasattr(current_node_for_walrus, 'children'):
                       # Example: (a := 10)
                       # Look for 'namedexpr_test' which contains 'name := test'
                       # This requires deeper inspection of parso's specific AST for named expressions
                       # For simplicity, this part is not fully implemented here.
                       pass


        for node in nodes_to_check:
            node_type = node.type
            # 할당문: a = 1 / a: int = 1 / a := 1 (Walrus)
            if node_type == 'simple_stmt' and len(node.children) > 0:
                first_child_stmt = node.children[0]
                if first_child_stmt.type == 'expr_stmt':
                    # Direct assignment: target = value
                    if len(first_child_stmt.children) >= 3 and first_child_stmt.children[1].type == 'operator' and \
                       first_child_stmt.children[1].value == '=':
                        _add_parso_target_names(first_child_stmt.children[0], defined_vars)
                    # AnnAssign: target ':' test ['=' test]
                    # Parso's expr_stmt can represent AnnAssign structure.
                    # Example: a : int = 10 -> expr_stmt(name, :, type, =, value)
                    # Example: a : int      -> expr_stmt(name, :, type)
                    elif len(first_child_stmt.children) >= 3 and first_child_stmt.children[1].type == 'operator' and first_child_stmt.children[1].value == ':':
                         _add_parso_target_names(first_child_stmt.children[0], defined_vars)

            # Walrus operator (NamedExpr) Python 3.8+
            # Parso represents 'name := expr' as 'namedexpr_test' often within 'atom_expr' or 'test'
            # This requires specific handling by traversing expressions.
            # A simplified check if a node directly represents a named expression:
            if node_type == 'namedexpr_test': # Example, actual type might vary
                 if len(node.children) >= 3 and node.children[1].type == 'operator' and node.children[1].value == ':=':
                      _add_parso_target_names(node.children[0], defined_vars)


            # 함수/클래스 정의
            elif node_type in ('funcdef', 'classdef'):
                name_node = node.children[1]
                if name_node.type == 'name' and isinstance(name_node, parso.tree.Leaf):
                    defined_vars.add(name_node.value)

            # Import 문
            elif node_type == 'simple_stmt' and len(node.children) > 0:
                 import_stmt = node.children[0]
                 if import_stmt.type in ('import_name', 'import_from'):
                      try:
                          for name_leaf in import_stmt.get_defined_names():
                               if name_leaf.value != '*': defined_vars.add(name_leaf.value)
                      except Exception as e: print(f"Error parsing import names: {e}", file=sys.stderr)

            # For 루프 변수
            elif node_type == 'for_stmt':
                 if len(node.children) >= 2:
                     _add_parso_target_names(node.children[1], defined_vars)

            # With ... as 변수
            elif node_type == 'with_stmt':
                 for item_child in node.children:
                      if item_child.type == 'with_item':
                           for sub_idx, sub_item_child in enumerate(item_child.children):
                               if isinstance(sub_item_child, parso.tree.Leaf) and sub_item_child.value == 'as':
                                    if sub_idx + 1 < len(item_child.children):
                                         _add_parso_target_names(item_child.children[sub_idx+1], defined_vars)
                                    break
            # Except ... as 변수
            elif node_type == 'try_stmt':
                 for child_of_try in node.children:
                      if child_of_try.type == 'except_clause':
                           as_found = False
                           for sub_child_of_except in child_of_try.children:
                               if as_found and sub_child_of_except.type == 'name':
                                    if isinstance(sub_child_of_except, parso.tree.Leaf): defined_vars.add(sub_child_of_except.value)
                                    break
                               if isinstance(sub_child_of_except, parso.tree.Leaf) and sub_child_of_except.value == 'as':
                                    as_found = True
                               elif as_found and sub_child_of_except.type != 'name':
                                    as_found = False
            # TODO: Comprehension 내부 변수 (x for x in ...): Parso는 별도 스코프 생성.

    except Exception as e:
         scope_repr = repr(scope_node); print(f"Error in collect_defined_variables_parso for {scope_repr[:100]}...: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr)
    return defined_vars


# --- Astroid 기반 함수 (이전과 동일하게 유지) ---
def get_type_astroid(node: astroid.NodeNG) -> Optional[str]:
    """astroid 노드의 타입을 추론합니다. (astroid infer 활용)"""
    try:
        inferred_list = list(node.infer(context=None))
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
    except Exception as e:
        node_repr = repr(node); print(f"Error in get_type_astroid for {node_repr[:100]}...: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr); return None

def is_compatible_astroid(type1_fq: Optional[str], type2_fq: Optional[str], op: str) -> bool:
    """두 타입(정규화된 이름 포함 가능)이 주어진 연산자에 대해 호환되는지 확인합니다."""
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
     """주어진 astroid 스코프 노드 내에서 정의된 변수 이름을 수집합니다."""
     # (이전 답변에서 제공한 Astroid 기반 collect_defined_variables 상세 로직 사용)
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