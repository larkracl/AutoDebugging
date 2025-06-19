# scripts/checkers/static_checkers/recursion_checker.py
import astroid
import sys

# *** 수정된 import 경로 ***
from checkers.base_checkers import BaseAstroidChecker

class StaticRecursionChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'W'; NAME = 'static-recursion'
    MSGS = {'0801': ("Potential recursion: Function '%s' calls itself (Static)", 'recursive-call','')}
    def check_function_recursion(self, func_node: astroid.FunctionDef):
        # print(f"DEBUG: Running {self.NAME} on function: {func_node.name}", file=sys.stderr)
        func_name = func_node.name
        try:
             for call_node in func_node.nodes_of_class(astroid.Call):
                 if isinstance(call_node.func, astroid.Name) and call_node.func.name == func_name:
                     if call_node.scope() is func_node:
                          print(f"DEBUG: {self.NAME} FOUND a recursive call in '{func_name}'", file=sys.stderr)
                          self.add_message(call_node.func, '0801', (func_name,)); return
        except Exception as e: print(f"Error checking recursion for {func_name}: {e}", file=sys.stderr)