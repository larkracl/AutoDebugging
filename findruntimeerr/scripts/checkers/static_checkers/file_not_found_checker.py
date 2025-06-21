# scripts/checkers/static_checkers/file_not_found_checker.py
import astroid
import os
import sys

from checkers.base_checkers import BaseAstroidChecker

class StaticFileNotFoundChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'W'
    NAME = 'static-file-not-found'
    node_types = (astroid.Call,)
    MSGS = {
        '0901': (
            "Potential FileNotFoundError: File '%s' might not exist (Static)",
            'file-not-found-warning',
            ''
        )
    }

    def check(self, node: astroid.Call):
        try:
            if (
                isinstance(node.func, astroid.Name)
                and node.func.name == 'open'
            ):
                print(f"DEBUG: {self.NAME} found an 'open' call.", file=sys.stderr)
                if (
                    node.args
                    and isinstance(node.args[0], astroid.Const)
                    and isinstance(node.args[0].value, str)
                ):
                    file_path_value = node.args[0].value
                    print(f"  [FileNotFound-DEBUG] Checking for file: '{file_path_value}'", file=sys.stderr)
                    if file_path_value and not os.path.isabs(file_path_value):
                        exists = os.path.exists(file_path_value)
                        print(f"  [FileNotFound-DEBUG] os.path.exists result: {exists}", file=sys.stderr)
                        if not exists:
                            print(f"DEBUG: {self.NAME} FOUND a potential FileNotFoundError for '{file_path_value}'", file=sys.stderr)
                            self.add_message(node.args[0], '0901', (file_path_value,))
        except Exception as e:
            print(f"Error in {self.NAME}.check: {e}", file=sys.stderr)