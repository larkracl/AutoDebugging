# scripts/checkers/static_checkers/file_not_found_checker.py
import astroid
import os
import sys

# *** 수정된 import 경로 ***
from checkers.base_checkers import BaseAstroidChecker

class StaticFileNotFoundChecker(BaseAstroidChecker):
     MSG_ID_PREFIX = 'W'; NAME = 'static-file-not-found'; node_types = (astroid.Call,)
     MSGS = {'0901': ("Potential FileNotFoundError: File '%s' might not exist (Static)", 'file-not-found-warning','')}
     def check(self, node: astroid.Call):
          # print(f"DEBUG: Running {self.NAME} on node: {node.as_string()}", file=sys.stderr)
          try:
              if isinstance(node.func, astroid.Name) and node.func.name == 'open':
                  if node.args and isinstance(node.args[0], astroid.Const) and isinstance(node.args[0].value, str):
                      file_path_value = node.args[0].value
                      if file_path_value and not os.path.isabs(file_path_value):
                          if not os.path.exists(file_path_value):
                              print(f"DEBUG: {self.NAME} FOUND a potential FileNotFoundError for '{file_path_value}'", file=sys.stderr)
                              self.add_message(node.args[0], '0901', (file_path_value,))
          except OSError as e: print(f"OSError checking file for {node.args[0].value if node.args and isinstance(node.args[0], astroid.Const) else 'N/A'}: {e}", file=sys.stderr)
          except Exception as e: print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)