# scripts/core.py
import parso
from parso.python import tree as pt
import astroid
import sys
import networkx as nx
from typing import List, Dict, Any, Optional, Tuple, cast
from networkx.readwrite import json_graph
import traceback

# 새로 만든 symbol_table 과 개선된 utils import
from symbol_table import Scope
from utils import populate_scope_from_parso
from utils import get_type_astroid, is_compatible_astroid, collect_defined_variables_astroid

# checkers에서 모든 필요한 클래스들을 명시적으로 가져옵니다.
from checkers import (
    RT_CHECKERS_CLASSES, 
    STATIC_CHECKERS_CLASSES,
    StaticRecursionChecker,
    BaseParsoChecker, 
    BaseAstroidChecker
)

class Linter:
    def __init__(self):
        print(f"[Linter.__init__] Initializing Linter", file=sys.stderr)
        self.parso_checkers: List[BaseParsoChecker] = []
        self.astroid_checkers: List[BaseAstroidChecker] = []
        self.errors: List[Dict[str, Any]] = []
        self.call_graph = nx.DiGraph()
        self.grammar: Optional[parso.Grammar] = None
        try:
            self.grammar = parso.load_grammar()
        except Exception as e:
            print(f"FATAL: Could not load parso grammar: {e}", file=sys.stderr)
        self._load_parso_checkers()

        # 스코프 관리용 속성
        self.root_scope: Optional[Scope] = None
        self.scope_map: Dict[int, Scope] = {}
        self.recursion_checker: Optional[StaticRecursionChecker] = None

    def _load_parso_checkers(self):
        if not self.grammar:
             print("[Linter._load_parso_checkers] Parso grammar not loaded. Skipping Parso checker loading.", file=sys.stderr)
             return
        checker_classes = RT_CHECKERS_CLASSES
        print(f"[Linter._load_parso_checkers] Loading {len(checker_classes)} Parso checkers (RT).", file=sys.stderr)
        for checker_class in checker_classes:
            try:
                checker_instance = checker_class(self)
                self.parso_checkers.append(checker_instance)
                print(f"[Linter._load_parso_checkers] Loaded Parso checker: {checker_class.__name__}", file=sys.stderr)
            except Exception as e:
                 self.add_message('CheckerInitError', None, f"Error initializing parso checker {checker_class.__name__}: {e}")

    def _build_and_visit_parso(self, node: parso.tree.BaseNode, current_scope: Scope):
        new_scope = current_scope
        if isinstance(node, (pt.Function, pt.Class, pt.Lambda)):
            if id(node) not in self.scope_map:
                new_scope = Scope(node, parent_scope=current_scope)
                self.scope_map[id(node)] = new_scope
                populate_scope_from_parso(new_scope)
            else:
                new_scope = self.scope_map[id(node)]

        for checker in self.parso_checkers:
            if not checker.node_types or node.type in checker.node_types:
                try:
                    checker.check(node, new_scope)
                except TypeError as te:
                    if "takes 2 positional arguments but 3 were given" in str(te):
                        try:
                            checker.check(node)
                        except Exception as e_inner:
                            error_msg = f"Error in legacy parso checker {checker.NAME}: {e_inner}"; print(error_msg, file=sys.stderr); traceback.print_exc(file=sys.stderr)
                            self.add_message('InternalParsoCheckerError', node, error_msg)
                    else:
                        error_msg = f"TypeError in parso checker {checker.NAME}: {te}"; print(error_msg, file=sys.stderr); traceback.print_exc(file=sys.stderr)
                        self.add_message('InternalParsoCheckerError', node, error_msg)
                except Exception as e:
                    error_msg = f"Error in parso checker {checker.NAME}: {e}"; print(error_msg, file=sys.stderr); traceback.print_exc(file=sys.stderr)
                    self.add_message('InternalParsoCheckerError', node, error_msg)

        if hasattr(node, 'children'):
            for child in node.children:
                self._build_and_visit_parso(child, new_scope)

    def get_scope_for_node(self, node: parso.tree.BaseNode) -> Optional[Scope]:
        current = node
        while current:
            scope_defining_node = current.get_parent_scope()
            if scope_defining_node and id(scope_defining_node) in self.scope_map:
                 return self.scope_map[id(scope_defining_node)]
            current = current.parent
        return self.root_scope

    def analyze_parso(self, tree: pt.Module):
        if not self.grammar:
             self.add_message('ParsoSetupError', None, "Parso grammar not loaded, cannot perform Parso analysis.")
             return
        self.root_scope = Scope(tree, parent_scope=None)
        self.scope_map = {id(tree): self.root_scope}
        print("[Linter.analyze_parso] Starting scope building and analysis...", file=sys.stderr)
        try:
            populate_scope_from_parso(self.root_scope)
            self._build_and_visit_parso(tree, self.root_scope)
        except Exception as e:
            print(f"!!! Exc during Parso AST traversal: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr)
            self.add_message('ParsoTraversalError', None, f"Error: {e}")
        print("[Linter.analyze_parso] Analysis finished.", file=sys.stderr)

    def add_message(self, msg_id: str, node: Optional[parso.tree.BaseNode], message: str):
        try:
            line, col, to_line, end_col = 1, 0, 1, 1
            if node:
                line, col = node.start_pos; to_line, end_col = node.end_pos
                line = max(1, line); col = max(0, col)
                to_line = max(line, to_line); end_col = max(col + 1, end_col)
            error_key = (msg_id, line, col, to_line, end_col)
            if not any(err.get('_key') == error_key for err in self.errors):
                self.errors.append({ 'message': message, 'line': line, 'column': col, 'to_line': to_line, 'end_column': end_col, 'errorType': msg_id, '_key': error_key })
        except Exception as e:
            print(f"Error adding parso message '{msg_id}': {e}", file=sys.stderr)
            fallback_key = (msg_id, 1, 0, 1, 1)
            if not any(err.get('_key') == fallback_key for err in self.errors):
                 self.errors.append({'message': message, 'line': 1, 'column': 0, 'to_line': 1, 'end_column': 1, 'errorType': msg_id, '_key': fallback_key})

    def add_astroid_message(self, msg_id: str, node: astroid.NodeNG, message: str):
         try:
             line = node.fromlineno or 1; col = node.col_offset or 0
             to_line = node.tolineno or line; end_col = node.end_col_offset or (col + 1)
             line = max(1, line); col = max(0, col); to_line = max(line, to_line); end_col = max(col + 1, end_col)
             error_key = (msg_id, line, col, to_line, end_col)
             if not any(err.get('_key') == error_key for err in self.errors):
                 print(f"DEBUG: [Astroid Linter] ADDING error: {msg_id} - {message}", file=sys.stderr)
                 self.errors.append({ 'message': message, 'line': line, 'column': col, 'to_line': to_line, 'end_column': end_col, 'errorType': msg_id, '_key': error_key })
         except Exception as e:
             print(f"Error adding astroid message '{msg_id}': {e}", file=sys.stderr)
             fallback_key = (msg_id, 1, 0, 1, 1)
             if not any(err.get('_key') == fallback_key for err in self.errors):
                  self.errors.append({'message': message, 'line': 1, 'column': 0, 'to_line': 1, 'end_column': 1, 'errorType': msg_id, '_key': fallback_key})

    def _load_astroid_checkers(self):
        if not self.astroid_checkers:
            checker_classes = STATIC_CHECKERS_CLASSES
            print(f"[Linter._load_astroid_checkers] Loading {len(checker_classes)} standard Astroid checkers.", file=sys.stderr)
            for CClass in checker_classes:
                try:
                    self.astroid_checkers.append(CClass(self))
                    print(f"[Linter._load_astroid_checkers] Loaded Astroid checker: {CClass.__name__}", file=sys.stderr)
                except Exception as e:
                    self.add_message('CheckerInitError', None, f"Error initializing astroid checker {CClass.__name__}: {e}")

            try:
                self.recursion_checker = StaticRecursionChecker(self)
                print(f"[Linter._load_astroid_checkers] Loaded Astroid checker: {StaticRecursionChecker.__name__}", file=sys.stderr)
            except Exception as e:
                self.add_message('CheckerInitError', None, f"Error initializing astroid checker {StaticRecursionChecker.__name__}: {e}")

    def visit_astroid_node(self, node: astroid.NodeNG):
         # StaticNameErrorChecker 디버깅을 위한 로그
         if isinstance(node, astroid.Name):
            print(f"\n[Core-DEBUG] Visiting Name node: '{node.name}' at L{node.lineno}", file=sys.stderr)

         try:
             if isinstance(node, astroid.FunctionDef): self.add_node_to_graph(node.qname(), type='function', lineno=node.fromlineno)
             elif isinstance(node, astroid.Call):
                  caller_qname = node.scope().qname() if hasattr(node.scope(), 'qname') else '<module>'
                  called_qname = None; call_type = 'calls'
                  try:
                       inferred = list(node.func.infer(context=None));
                       if inferred and inferred[0] is not astroid.Uninferable:
                            called_qname = getattr(inferred[0], 'qname', getattr(inferred[0], 'name', None));
                            if isinstance(inferred[0], astroid.BoundMethod): call_type = 'calls_method'
                  except astroid.InferenceError: pass
                  if caller_qname and called_qname: self.add_edge_to_graph(caller_qname, called_qname, type=call_type, lineno=node.fromlineno)
             elif isinstance(node, astroid.ClassDef): self.add_node_to_graph(node.qname(), type='class', lineno=node.fromlineno)
         except Exception as e: print(f"Error building graph for astroid node: {repr(node)[:100]}...: {e}", file=sys.stderr)

         for checker in self.astroid_checkers:
             if not checker.node_types or isinstance(node, checker.node_types):
                 try:
                      if hasattr(checker, 'check') and callable(checker.check):
                          # StaticNameErrorChecker에 대한 추가 디버깅
                          if checker.NAME == 'static-name-error':
                              print(f"  [Core-DEBUG] Calling StaticNameErrorChecker.check for '{node.name}'", file=sys.stderr)
                          checker.check(node)
                 except Exception as e:
                      error_msg = f"Error in astroid checker {checker.NAME} on node {node.as_string()}: \n{traceback.format_exc()}"; print(error_msg, file=sys.stderr)
                      self.add_astroid_message('InternalAstroidCheckerError', node, error_msg)

         for child in node.get_children():
             self.visit_astroid_node(child)

    def analyze_astroid(self, tree: astroid.Module):
        self._load_astroid_checkers()
        self.call_graph = nx.DiGraph()
        print("[Linter.analyze_astroid] Starting analysis (astroid)...", file=sys.stderr)
        try:
            self.visit_astroid_node(tree)

            if self.recursion_checker:
                # --- 수정된 부분: print 문을 stderr로 변경 ---
                print(f"[Linter.analyze_astroid] Running {self.recursion_checker.NAME} for recursion.", file=sys.stderr)
                try:
                    for func_node in tree.nodes_of_class(astroid.FunctionDef):
                        self.recursion_checker.check_function_recursion(func_node)
                except Exception as e:
                    print(f"Error in recursion checker {self.recursion_checker.NAME}: {e}", file=sys.stderr)

        except Exception as e:
            print(f"!!! Exc during Astroid AST traversal: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr)
            self.add_message('AstroidTraversalError', None, f"Error: {e}")
        print("[Linter.analyze_astroid] Analysis finished.", file=sys.stderr)

    def add_node_to_graph(self, node_name: str, **kwargs):
        if not isinstance(node_name, str) or not node_name: return
        if node_name not in self.call_graph: self.call_graph.add_node(node_name, **kwargs)
        else:
            nd = self.call_graph.nodes[node_name]
            for k, v in kwargs.items():
                 if k == 'lineno' and 'lineno' not in nd: nd[k] = v
                 elif nd.get(k) in (None, 'unknown'): nd[k] = v

    def add_edge_to_graph(self, caller: str, callee: str, **kwargs):
        if not isinstance(caller, str) or not caller or not isinstance(callee, str) or not callee: return
        self.add_node_to_graph(caller, type='unknown'); self.add_node_to_graph(callee, type='unknown')
        ln = kwargs.pop('lineno', None); ed = kwargs
        if self.call_graph.has_edge(caller, callee):
            exd = self.call_graph.edges[caller, callee]
            if 'call_sites' in exd and ln is not None:
                 if ln not in exd['call_sites']: exd['call_sites'].append(ln); exd['call_sites'].sort()
            elif ln is not None: exd['call_sites'] = [ln]
            for k, v in ed.items():
                 if k not in exd or exd.get(k) == 'unknown': exd[k] = v
        else:
             if ln is not None: ed['call_sites'] = [ln]
             self.call_graph.add_edge(caller, callee, **ed)


def analyze_code(code: str, mode: str = 'realtime') -> Dict[str, Any]:
    # ... (analyze_code 함수는 변경 없음, 그대로 유지) ...
    print(f"analyze_code (Mode-Separated) called with mode: {mode}", file=sys.stderr)
    linter = Linter()
    call_graph_data: Optional[Dict[str, Any]] = None
    all_errors: List[Dict[str, Any]] = []

    if mode == 'realtime':
        syntax_errors: List[Dict[str, Any]] = []
        parso_tree: Optional[pt.Module] = None
        if not linter.grammar:
             linter.add_message("ParsoSetupError", None, "Failed to load Parso grammar.")
        else:
            try:
                parso_tree = linter.grammar.parse(code, error_recovery=True)
                print(f"Parso AST parsed for realtime.", file=sys.stderr)
                for error in linter.grammar.iter_errors(parso_tree):
                     line, col = error.start_pos; to_line, end_col = error.end_pos
                     syntax_errors.append({'message': f"SyntaxError: {error.message}", 'line': line, 'column': col, 'to_line': to_line, 'end_column': max(col + 1, end_col), 'errorType': 'SyntaxError'})
                print(f"Found {len(syntax_errors)} syntax errors.", file=sys.stderr)
            except Exception as e:
                 linter.add_message('ParsoCrashError', None, f"Critical Parso parsing error: {e}")
        if parso_tree is not None: linter.analyze_parso(parso_tree)
        all_errors = syntax_errors + linter.errors

    elif mode == 'static':
        astroid_tree: Optional[astroid.Module] = None
        try:
            astroid_tree = astroid.parse(code, module_name='<string>')
            print(f"Astroid AST parsed for static analysis.", file=sys.stderr)
        except SyntaxError as e:
            error = {'message': f"SyntaxError: {e.msg}", 'line': e.lineno or 1, 'column': (e.offset or 1) - 1, 'to_line': e.lineno or 1, 'end_column': (e.offset or 1), 'errorType': 'SyntaxError'}
            all_errors.append(error)
        except Exception as e:
             linter.add_message('AstroidParsingError', None, f"Error parsing with Astroid: {e}")
             all_errors = linter.errors
        if astroid_tree is not None:
            linter.analyze_astroid(astroid_tree)
            try:
                if linter.call_graph.nodes: call_graph_data = json_graph.node_link_data(linter.call_graph)
            except Exception as e: linter.add_message('GraphError', None, f"Failed to convert call graph: {e}")
            all_errors = linter.errors

    else:
        all_errors = [{'message': f"Unknown analysis mode: {mode}", 'line': 1, 'column': 0, 'to_line': 1, 'end_column': 1, 'errorType': 'ModeError'}]

    cleaned_errors = [{k: v for k, v in err.items() if k != '_key'} for err in all_errors]
    result = {'errors': cleaned_errors, 'call_graph': call_graph_data}
    print(f"analyze_code returning {len(result['errors'])} errors for mode '{mode}'.", file=sys.stderr)
    return result