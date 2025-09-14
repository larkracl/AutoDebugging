# scripts/checkers/static_checkers/file_not_found_checker.py
import astroid
import sys
import traceback

from checkers.base_checkers import BaseAstroidChecker

class StaticFileNotFoundChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'
    NAME = 'static-file-not-found'
    node_types = (astroid.Call,)
    MSGS = {
        '0601': ("FileNotFoundError: File '%s' not found (Static)", 'file-not-found', '')
    }

    def check(self, node: astroid.Call):
        try:
            if isinstance(node.func, astroid.Name) and node.func.name == 'open':
                if node.args and isinstance(node.args[0], astroid.Const):
                    file_path = node.args[0].value
                    if isinstance(file_path, str):
                        # 테스트 파일이나 임시 파일은 무시
                        if (file_path.startswith('test') and file_path.endswith('.csv')) or \
                           file_path.startswith('temp_') or \
                           file_path.startswith('tmp_'):
                            return
                        
                        import os
                        if not os.path.exists(file_path):
                            self.add_message(node, '0601', (file_path,))
        except Exception as e:
            print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)