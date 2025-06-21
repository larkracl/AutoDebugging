# scripts/core.py
import parso
from parso.python import tree as pt
import astroid
import sys
import networkx as nx
from typing import List, Dict, Any, Optional, Tuple, cast
from networkx.readwrite import json_graph
import traceback

from symbol_table import Scope
from utils import populate_scope_from_parso, get_type_astroid

from checkers import (
    RT_CHECKERS_CLASSES, 
    STATIC_CHECKERS_CLASSES,
    StaticRecursionChecker,
    BaseParsoChecker, 
    BaseAstroidChecker
)

class Linter:
    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir
        self.parso_checkers: List[BaseParsoChecker] = []
        self.astroid_checkers: List[BaseAstroidChecker] = []
        self.errors: List[Dict[str, Any]] = []
        self.call_graph = nx.DiGraph()
        self.grammar: Optional[parso.Grammar] = None
        self.recursion_checker: Optional[StaticRecursionChecker] = None
        try:
            self.grammar = parso.load_grammar()
        except Exception:
            # 에러 발생 시 조용히 실패 (오류 메시지는 상위에서 처리)
            pass
        self._load_parso_checkers()

    def _load_parso_checkers(self):
        if not self.grammar: return
        for checker_class in RT_CHECKERS_CLASSES:
            try:
                self.parso_checkers.append(checker_class(self))
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
                except Exception as e:
                    self.add_message('InternalParsoCheckerError', node, f"Error in parso checker {checker.NAME}: {e}")
        
        if hasattr(node, 'children'):
            for child in node.children:
                self._build_and_visit_parso(child, new_scope)

    def analyze_parso(self, tree: pt.Module):
        if not self.grammar:
             self.add_message('ParsoSetupError', None, "Parso grammar not loaded.")
             return
        self.root_scope = Scope(tree, parent_scope=None)
        self.scope_map = {id(tree): self.root_scope}
        try:
            populate_scope_from_parso(self.root_scope)
            self._build_and_visit_parso(tree, self.root_scope)
        except Exception as e:
            self.add_message('ParsoTraversalError', None, f"Error during Parso AST traversal: {e}")

    def add_message(self, msg_id: str, node: Optional[parso.tree.BaseNode], message: str):
        try:
            line, col, to_line, end_col = 1, 0, 1, 1
            if node:
                line, col = node.start_pos
                to_line, end_col = node.end_pos
                line, col = max(1, line), max(0, col)
                to_line, end_col = max(line, to_line), max(col + 1, end_col)
            error_key = (msg_id, line, col, to_line, end_col)
            if not any(err.get('_key') == error_key for err in self.errors):
                self.errors.append({'message': message, 'line': line, 'column': col, 'to_line': to_line, 'end_column': end_col, 'errorType': msg_id, '_key': error_key})
        except Exception:
            pass

    def add_astroid_message(self, msg_id: str, node: astroid.NodeNG, message: str):
         try:
             line = node.fromlineno or 1
             col = node.col_offset or 0
             to_line = node.tolineno or line
             end_col = node.end_col_offset or (col + 1)
             line, col = max(1, line), max(0, col)
             to_line, end_col = max(line, to_line), max(col + 1, end_col)
             error_key = (msg_id, line, col, to_line, end_col)
             if not any(err.get('_key') == error_key for err in self.errors):
                 self.errors.append({'message': message, 'line': line, 'column': col, 'to_line': to_line, 'end_column': end_col, 'errorType': msg_id, '_key': error_key})
         except Exception:
             pass

    def _load_astroid_checkers(self):
        if not self.astroid_checkers:
            for CClass in STATIC_CHECKERS_CLASSES:
                try:
                    self.astroid_checkers.append(CClass(self))
                except Exception as e:
                    self.add_message('CheckerInitError', None, f"Error initializing astroid checker {CClass.__name__}: {e}")
            try:
                self.recursion_checker = StaticRecursionChecker(self)
            except Exception as e:
                self.add_message('CheckerInitError', None, f"Error initializing astroid checker {StaticRecursionChecker.__name__}: {e}")

    def visit_astroid_node(self, node: astroid.NodeNG):
         try:
             if isinstance(node, astroid.FunctionDef): self.add_node_to_graph(node.qname(), type='function', lineno=node.fromlineno)
             elif isinstance(node, astroid.Call):
                  caller_qname = node.scope().qname() if hasattr(node.scope(), 'qname') else '<module>'
                  called_qname = None
                  try:
                       inferred = next(node.func.infer(context=None), None)
                       if inferred: called_qname = getattr(inferred, 'qname', getattr(inferred, 'name', None))
                  except (astroid.InferenceError, StopIteration): pass
                  if caller_qname and called_qname: self.add_edge_to_graph(caller_qname, called_qname, lineno=node.fromlineno)
             elif isinstance(node, astroid.ClassDef): self.add_node_to_graph(node.qname(), type='class', lineno=node.fromlineno)
         except Exception: pass

         for checker in self.astroid_checkers:
             if not checker.node_types or isinstance(node, checker.node_types):
                 try:
                    checker.check(node)
                 except Exception as e:
                      error_msg = f"Error in astroid checker {checker.NAME} on node {node.as_string()}: \n{traceback.format_exc()}"
                      self.add_astroid_message('InternalAstroidCheckerError', node, error_msg)

         for child in node.get_children():
             self.visit_astroid_node(child)

    def analyze_astroid(self, tree: astroid.Module):
        self._load_astroid_checkers()
        self.call_graph = nx.DiGraph()
        try:
            self.visit_astroid_node(tree)
            if self.recursion_checker:
                for func_node in tree.nodes_of_class(astroid.FunctionDef):
                    self.recursion_checker.check_function_recursion(func_node)
        except Exception as e:
            self.add_message('AstroidTraversalError', None, f"Error during Astroid AST traversal: {e}")
    
    def add_node_to_graph(self, node_name: str, **kwargs):
        if not isinstance(node_name, str) or not node_name: return
        if node_name not in self.call_graph: self.call_graph.add_node(node_name, **kwargs)
    
    def add_edge_to_graph(self, caller: str, callee: str, **kwargs):
        if not isinstance(caller, str) or not caller or not isinstance(callee, str) or not callee: return
        self.add_node_to_graph(caller); self.add_node_to_graph(callee)
        if not self.call_graph.has_edge(caller, callee): self.call_graph.add_edge(caller, callee, **kwargs)

def analyze_code(code: str, mode: str = 'realtime', base_dir: Optional[str] = None) -> Dict[str, Any]:
    linter = Linter(base_dir=base_dir)
    call_graph_data: Optional[Dict[str, Any]] = None
    all_errors: List[Dict[str, Any]] = []

    if mode == 'realtime':
        parso_tree = None
        if linter.grammar:
            try:
                parso_tree = linter.grammar.parse(code, error_recovery=True)
                for error in linter.grammar.iter_errors(parso_tree):
                     all_errors.append({'message': f"SyntaxError: {error.message}", 'line': error.start_pos[0], 'column': error.start_pos[1], 'errorType': 'SyntaxError'})
            except Exception as e:
                 linter.add_message('ParsoCrashError', None, f"Critical Parso parsing error: {e}")
        if parso_tree is not None:
            linter.analyze_parso(parso_tree)
        all_errors.extend(linter.errors)
    elif mode == 'static':
        astroid_tree = None
        try:
            astroid_tree = astroid.parse(code, module_name='<string>')
        except SyntaxError as e:
            all_errors.append({'message': f"SyntaxError: {e.msg}", 'line': e.lineno or 1, 'column': (e.offset or 1) - 1, 'errorType': 'SyntaxError'})
        except Exception as e:
            linter.add_message('AstroidParsingError', None, f"Error parsing with Astroid: {e}")
        
        if astroid_tree is not None:
            linter.analyze_astroid(astroid_tree)
            try:
                if linter.call_graph.nodes: call_graph_data = json_graph.node_link_data(linter.call_graph)
            except Exception as e: linter.add_message('GraphError', None, f"Failed to convert call graph: {e}")
        all_errors.extend(linter.errors)
    else:
        all_errors.append({'message': f"Unknown analysis mode: {mode}", 'line': 1, 'column': 0, 'errorType': 'ModeError'})

    cleaned_errors = [{k: v for k, v in err.items() if k != '_key'} for err in all_errors]
    result = {'errors': cleaned_errors, 'call_graph': call_graph_data}
    return result