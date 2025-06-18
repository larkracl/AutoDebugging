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
        self.def_node = def_node
        self.references: List[parso.tree.BaseNode] = []

    def __repr__(self):
        return f"Symbol(name='{self.name}', type={self.type.name})"

class Scope:
    """스코프와 그 안에 정의된 심볼들을 관리하는 심볼 테이블 클래스."""
    def __init__(self, scope_node: parso.tree.BaseNode, parent_scope: Optional[Scope] = None):
        self.node = scope_node
        self.parent = parent_scope
        self.symbols: Dict[str, Symbol] = {}

    def define(self, symbol: Symbol):
        self.symbols[symbol.name] = symbol

    def lookup(self, name: str, search_parents: bool = True) -> Optional[Symbol]:
        symbol = self.symbols.get(name)
        if symbol:
            return symbol
        if search_parents and self.parent:
            return self.parent.lookup(name, search_parents=True)
        if hasattr(builtins, name):
            return Symbol(name, SymbolType.BUILTIN, None)
        return None

    def __repr__(self):
        scope_type = self.node.type if hasattr(self.node, 'type') else 'GLOBAL'
        parent_type = self.parent.node.type if self.parent and hasattr(self.parent.node, 'type') else 'None'
        return f"<Scope type={scope_type} parent={parent_type} symbols={list(self.symbols.keys())}>"