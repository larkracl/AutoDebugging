# core.py (Parso + Astroid 병행, Linter에 grammar 추가)
import parso
import astroid
import sys
import networkx as nx
from typing import List, Dict, Any, Set, Tuple, Optional, Union, cast # cast 추가
from parso.python import tree as pt # pt import 추가

from utils import collect_defined_variables_parso
from utils import get_type_astroid, is_compatible_astroid, collect_defined_variables_astroid
from checkers import RT_CHECKERS_CLASSES, STATIC_CHECKERS_CLASSES
from checkers import BaseParsoChecker, BaseAstroidChecker
from networkx.readwrite import json_graph
import traceback

class Linter:
    """Parso AST 순회 및 조건부 Astroid 분석 실행."""
    def __init__(self):
        print(f"[Linter.__init__] Initializing Linter (Parso based for RT)", file=sys.stderr)
        self.parso_checkers: List[BaseParsoChecker] = []
        self.astroid_checkers: List[BaseAstroidChecker] = []
        self.errors: List[Dict[str, Any]] = []
        self.call_graph = nx.DiGraph()
        self.current_parso_node: Optional[parso.tree.BaseNode] = None
        self.grammar: Optional[parso.Grammar] = None # 타입 명시
        try:
            self.grammar = parso.load_grammar() # Parso grammar 객체 저장
        except Exception as e:
            print(f"FATAL: Could not load parso grammar: {e}", file=sys.stderr)
            # self.grammar remains None
        self._load_parso_checkers()

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

    def add_message(self, msg_id: str, node: Optional[parso.tree.BaseNode], message: str):
        try:
            line, col, to_line, end_col = 1, 0, 1, 1
            if node:
                line, col = node.start_pos # Parso: 1-based line, 0-based col
                to_line, end_col = node.end_pos
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
             line = node.fromlineno or 1; col = node.col_offset or 0 # Astroid: 1-based line, 0-based col
             to_line = node.tolineno or line; end_col = node.end_col_offset or (col + 1)
             line = max(1, line); col = max(0, col); to_line = max(line, to_line); end_col = max(col + 1, end_col)
             error_key = (msg_id, line, col, to_line, end_col)
             if not any(err.get('_key') == error_key for err in self.errors):
                 self.errors.append({ 'message': message, 'line': line, 'column': col, 'to_line': to_line, 'end_column': end_col, 'errorType': msg_id, '_key': error_key })
         except Exception as e:
             print(f"Error adding astroid message '{msg_id}': {e}", file=sys.stderr)
             fallback_key = (msg_id, 1, 0, 1, 1)
             if not any(err.get('_key') == fallback_key for err in self.errors):
                  self.errors.append({'message': message, 'line': 1, 'column': 0, 'to_line': 1, 'end_column': 1, 'errorType': msg_id, '_key': fallback_key})

    def get_current_scope_variables_parso(self) -> Set[str]:
        if self.current_parso_node:
             try:
                 scope = self.current_parso_node
                 while scope and scope.type not in ('file_input', 'funcdef', 'classdef', 'lambdef'):
                       scope = scope.parent
                 if scope and isinstance(scope, (pt.Module, pt.Function, pt.Class, pt.Lambda)):
                     return collect_defined_variables_parso(scope)
                 elif scope is None and self.current_parso_node.type == 'file_input': # parso.tree.Module is file_input
                      return collect_defined_variables_parso(cast(pt.Module, self.current_parso_node))
             except Exception as e:
                  node_repr = repr(self.current_parso_node); print(f"Error getting parso scope vars for {node_repr[:100]}...: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr)
        return set()

    def visit_parso_node(self, node: parso.tree.BaseNode):
         if not self.grammar: return
         self.current_parso_node = node
         node_type_str = node.type
         for checker in self.parso_checkers:
             if not checker.node_types or node_type_str in checker.node_types:
                 try:
                      if hasattr(checker, 'check') and callable(checker.check): checker.check(node)
                 except Exception as e:
                     error_msg = f"Error in parso checker {checker.NAME}: {e}"; print(error_msg, file=sys.stderr); traceback.print_exc(file=sys.stderr)
                     self.add_message('InternalParsoCheckerError', node, error_msg)
         if hasattr(node, 'children'):
             for child in node.children: self.visit_parso_node(child)

    def analyze_parso(self, tree: parso.python.tree.Module):
        if not self.grammar:
             self.add_message('ParsoSetupError', None, "Parso grammar not loaded, cannot perform Parso analysis.")
             return
        self.current_parso_node = None
        print("[Linter.analyze_parso] Starting analysis (parso)...", file=sys.stderr)
        try: self.visit_parso_node(tree)
        except Exception as e: print(f"!!! Exc during Parso AST traversal: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr); self.add_message('ParsoTraversalError', None, f"Error during Parso AST traversal: {e}")
        print("[Linter.analyze_parso] Analysis finished (parso).", file=sys.stderr)

    def _load_astroid_checkers(self):
        if not self.astroid_checkers:
             checker_classes = STATIC_CHECKERS_CLASSES
             print(f"[Linter._load_astroid_checkers] Loading {len(checker_classes)} Astroid checkers.", file=sys.stderr)
             for CClass in checker_classes:
                 try: self.astroid_checkers.append(CClass(self)); print(f"[Linter._load_astroid_checkers] Loaded Astroid checker: {CClass.__name__}", file=sys.stderr)
                 except Exception as e: self.add_message('CheckerInitError', None, f"Error initializing astroid checker {CClass.__name__}: {e}")

    def visit_astroid_node(self, node: astroid.NodeNG):
         try:
             if isinstance(node, astroid.FunctionDef): self.add_node_to_graph(node.qname(), type='function', lineno=node.fromlineno)
             elif isinstance(node, astroid.Call):
                  caller_qname = node.scope().qname() if hasattr(node.scope(), 'qname') else '<module>'
                  called_qname = None; call_type = 'calls'
                  try:
                       inferred = list(node.func.infer(context=None));
                       if inferred and inferred[0] is not astroid.Uninferable: called_qname = getattr(inferred[0], 'qname', getattr(inferred[0], 'name', None));
                       if inferred and isinstance(inferred[0], astroid.BoundMethod): call_type = 'calls_method' # Check inferred[0] exists
                  except astroid.InferenceError: pass
                  if caller_qname and called_qname: self.add_edge_to_graph(caller_qname, called_qname, type=call_type, lineno=node.fromlineno)
             elif isinstance(node, astroid.ClassDef): self.add_node_to_graph(node.qname(), type='class', lineno=node.fromlineno)
         except Exception as e: print(f"Error building graph for astroid node: {repr(node)[:100]}...: {e}", file=sys.stderr)
         for checker in self.astroid_checkers:
             if not checker.node_types or isinstance(node, checker.node_types):
                 try:
                      if hasattr(checker, 'check') and callable(checker.check): checker.check(node)
                 except Exception as e: error_msg = f"Error in astroid checker {checker.NAME}: {e}"; print(error_msg, file=sys.stderr); traceback.print_exc(file=sys.stderr); self.add_astroid_message('InternalAstroidCheckerError', node, error_msg)
         for child in node.get_children(): self.visit_astroid_node(child)

    def analyze_astroid(self, tree: astroid.Module):
        self._load_astroid_checkers(); self.call_graph = nx.DiGraph()
        print("[Linter.analyze_astroid] Starting analysis (astroid)...", file=sys.stderr)
        try:
            self.visit_astroid_node(tree)
            print("[Linter.analyze_astroid] Running function-level astroid checkers...", file=sys.stderr)
            for checker in self.astroid_checkers:
                if hasattr(checker, 'check_function_recursion') and callable(checker.check_function_recursion): # check_function_recursion for astroid
                     print(f"[Linter.analyze_astroid] Running {checker.NAME} for recursion.")
                     try:
                          for func_node in tree.nodes_of_class(astroid.FunctionDef): checker.check_function_recursion(func_node)
                     except Exception as e: print(f"Error in recursion checker {checker.NAME}: {e}", file=sys.stderr)
        except Exception as e: print(f"!!! Exc during Astroid AST traversal: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr); self.add_message('AstroidTraversalError', None, f"Error: {e}")
        print("[Linter.analyze_astroid] Analysis finished (astroid).", file=sys.stderr)

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
    print(f"analyze_code (Parso+Astroid) called with mode: {mode}", file=sys.stderr)
    syntax_errors: List[Dict[str, Any]] = []; call_graph_data: Optional[Dict[str, Any]] = None
    linter = Linter()
    parso_tree: Optional[parso.python.tree.Module] = None
    if not linter.grammar:
         print("Parso grammar not loaded, skipping Parso analysis stage.", file=sys.stderr)
         linter.add_message("ParsoSetupError", None, "Failed to load Parso grammar. Analysis incomplete.")
    else:
        try:
            parso_tree = linter.grammar.parse(code, error_recovery=True)
            print(f"Parso AST parsed (error recovery enabled)", file=sys.stderr)
            for error in linter.grammar.iter_errors(parso_tree):
                 line, col = error.start_pos; to_line, end_col = error.end_pos
                 syntax_errors.append({'message': f"SyntaxError: {error.message}", 'line': line, 'column': col, 'to_line': to_line, 'end_column': max(col + 1, end_col), 'errorType': 'SyntaxError'})
            print(f"Found {len(syntax_errors)} syntax errors during parso parsing.", file=sys.stderr)
        except Exception as e: print(f"!!! CRITICAL Exc during parso parsing: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr); linter.add_message('ParsoCrashError', None, f"Critical Parso parsing error: {e}"); parso_tree = None

    if parso_tree is not None: linter.analyze_parso(parso_tree)
    astroid_tree: Optional[astroid.Module] = None
    run_astroid_analysis = (not syntax_errors and mode == 'static')
    if run_astroid_analysis:
        print("[analyze_code] No syntax errors, mode 'static'. Proceeding with Astroid.", file=sys.stderr)
        try: astroid_tree = astroid.parse(code, module_name='<string>'); print(f"Astroid AST parsed for static analysis.", file=sys.stderr)
        except SyntaxError as e: print(f"UNEXPECTED SyntaxError in astroid (static): {e}", file=sys.stderr); l, c = e.lineno or 1, (e.offset or 1) -1; linter.add_message('AstroidSyntaxError', None, f"Astroid SyntaxError: {e.msg} L{l}:C{c+1}")
        except Exception as e: print(f"!!! Exc in astroid parsing (static): {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr); linter.add_message('AstroidParsingError', None, f"Error parsing with Astroid: {e}")
        if astroid_tree is not None:
            linter.analyze_astroid(astroid_tree)
            try:
                if linter.call_graph.nodes: call_graph_data = json_graph.node_link_data(linter.call_graph); print("[analyze_code] Call graph generated.", file=sys.stderr)
                else: print("[analyze_code] Call graph empty.", file=sys.stderr); call_graph_data = None
            except ImportError: print("Error: networkx not found for graph.", file=sys.stderr); linter.add_message('GraphError', None, "networkx not found."); call_graph_data = None
            except Exception as e: print(f"Error converting graph: {e}", file=sys.stderr); linter.add_message('GraphError', None, f"Failed to convert graph: {e}"); call_graph_data = None
    elif mode == 'static': print("[analyze_code] Syntax errors present. Skipping Astroid for static mode.", file=sys.stderr)
    all_errors = syntax_errors + linter.errors
    cleaned_errors = [{k: v for k, v in err.items() if k != '_key'} for err in all_errors]
    result = {'errors': cleaned_errors, 'call_graph': call_graph_data}
    if not isinstance(result.get('errors'), list): result['errors'] = []
    print(f"analyze_code returning {len(result['errors'])} total errors.", file=sys.stderr)
    return result