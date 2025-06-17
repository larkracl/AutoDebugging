# scripts/symbol_table.py
from __future__ import annotations
from enum import Enum, auto
from typing import Dict, Optional, List
import parso
import builtins

class SymbolType(Enum):
    VARIABLE = auto()
    FUNCTION = auto()
    CLASS = auto()
    PARAMETER = auto()
    MODULE = auto()
    IMPORTED_NAME = auto()
    BUILTIN = auto()

class Symbol:
    """코드 내의 이름(변수, 함수, 클래스 등)에 대한 정보를 저장하는 클래스."""
    def __init__(self, name: str, symbol_type: SymbolType, def_node: Optional[parso.tree.BaseNode]):
        self.name = name
        self.type = symbol_type
        self.def_node = def_node # 정의가 일어난 Parso 노드
        self.references: List[parso.tree.BaseNode] = [] # 이 심볼이 사용된 모든 위치 (선택적 확장)

    def __repr__(self):
        return f"Symbol(name='{self.name}', type={self.type.name})"

class Scope:
    """스코프와 그 안에 정의된 심볼들을 관리하는 심볼 테이블 클래스."""
    def __init__(self, scope_node: parso.tree.BaseNode, parent_scope: Optional[Scope] = None):
        self.node = scope_node # 이 스코프를 정의하는 Parso 노드 (e.g., Module, FunctionDef)
        self.parent = parent_scope # 부모 스코프
        self.symbols: Dict[str, Symbol] = {} # {이름: Symbol 객체}

    def define(self, symbol: Symbol):
        """현재 스코프에 새로운 심볼을 정의합니다."""
        if symbol.name in self.symbols:
            # TODO: 이름 재정의(redefinition) 경고 처리 가능
            pass
        self.symbols[symbol.name] = symbol

    def lookup(self, name: str, search_parents: bool = True) -> Optional[Symbol]:
        """
        주어진 이름에 해당하는 심볼을 찾습니다.
        먼저 현재 스코프에서 찾고, 없으면 부모 스코프를 재귀적으로 검색합니다.
        """
        # 1. 현재 스코프에서 찾기
        symbol = self.symbols.get(name)
        if symbol:
            return symbol

        # 2. 부모 스코프에서 찾기 (search_parents 옵션 활성화 시)
        if search_parents and self.parent:
            return self.parent.lookup(name, search_parents=True)

        # 3. 내장(built-in) 스코프 확인
        if hasattr(builtins, name):
            return Symbol(name, SymbolType.BUILTIN, None)

        # 모든 스코프에서 찾지 못함
        return None

    def __repr__(self):
        scope_type = self.node.type if hasattr(self.node, 'type') else 'GLOBAL'
        parent_type = self.parent.node.type if self.parent and hasattr(self.parent.node, 'type') else 'None'
        return f"<Scope type={scope_type} parent={parent_type} symbols={list(self.symbols.keys())}>"