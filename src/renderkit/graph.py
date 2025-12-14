import graphlib
from typing import Any, Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from jinja2 import Environment, meta
from pathlib import Path
from .console import rich_debug
import typer

@dataclass
class Node:
    key_path: str        # e.g., "bug_repro.command_to_run"
    raw_value: Any       # e.g., "$!{{ tool }} ..."
    dependencies: Set[str]
    namespace: str       # e.g., "bug_repro" (or "" for root)

class DependencyGraph:
    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.env = Environment(autoescape=False)

    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = '', namespace: str = '') -> List[Tuple[str, Any, str]]:
        """
        递归地将嵌套字典扁平化为 (key_path, value, namespace) 的列表。
        namespace 仅在顶层确定，后续递归保持不变。
        """
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}.{k}" if parent_key else k
            
            # 确定命名空间：如果是顶层键，它就是命名空间；否则沿用父级的
            current_ns = k if parent_key == '' else namespace
            
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, current_ns))
            else:
                items.append((new_key, v, current_ns))
        return items

    def build(self, context: Dict[str, Any]):
        """
        从原始上下文中构建依赖图。
        分为两步：
        1. 创建所有节点。
        2. 解析每个节点的依赖关系并建立连接。
        """
        flat_items = self._flatten_dict(context)
        
        # Step 1: Create Nodes
        for key_path, value, ns in flat_items:
            # 初始时不解析依赖，只存储基本信息
            self.nodes[key_path] = Node(key_path, value, set(), ns)

        # Step 2: Resolve Dependencies & Link
        all_keys = set(self.nodes.keys())

        for node in self.nodes.values():
            if not isinstance(node.raw_value, str):
                continue

            # Determine template source
            # 我们需要扫描所有字符串以发现潜在的依赖，即使它是静态的
            # (例如 target: "{{ dep }}")，以便按需加载能正确工作。
            template_src = node.raw_value
            if node.raw_value.startswith('$'):
                template_src = node.raw_value[1:]
            
            try:
                ast = self.env.parse(template_src)
                raw_vars = meta.find_undeclared_variables(ast)
            except Exception as e:
                rich_debug(f"[Graph] 解析模板失败 '{node.key_path}': {e}")
                continue

            for var in raw_vars:
                # 依赖解析策略：
                # 1. 尝试在同命名空间下查找 (e.g. bug_repro.target -> bug_repro.tool)
                if node.namespace:
                    sibling = f"{node.namespace}.{var}"
                    if sibling in all_keys:
                        node.dependencies.add(sibling)
                        continue # 找到即止

                # 2. 尝试全局查找 (e.g. tool_path)
                if var in all_keys:
                    node.dependencies.add(var)
                    continue

                # 3. 尝试作为命名空间前缀查找 (e.g. var="KOS" -> matches "KOS.version")
                # 这对于引用整个对象至关重要
                found_prefix = False
                for key in all_keys:
                    if key.startswith(f"{var}."):
                        node.dependencies.add(key)
                        found_prefix = True
                
                if found_prefix:
                    continue

    def _get_required_subgraph(self, target_keys: Optional[Set[str]]) -> Set[str]:
        """
        计算目标节点所需的最小子图（所有上游依赖）。
        如果 target_keys 为 None 或空，返回所有节点（全量模式）。
        """
        if not target_keys:
            return set(self.nodes.keys())

        required_nodes = set()
        visited = set()
        
        # 1. 确定初始节点集合
        # 这一步必须处理 CLI 传入的变量名可能只是命名空间的情况
        initial_nodes = set()
        for req in target_keys:
            # Case A: Exact match
            if req in self.nodes:
                initial_nodes.add(req)
            
            # Case B: Prefix match (Requesting a namespace)
            # e.g. req="KOS" -> matches "KOS.version", "KOS.author"
            for node_key in self.nodes:
                if node_key.startswith(f"{req}."):
                    initial_nodes.add(node_key)
                # Case C: Suffix match (Scope injection shortcut)
                # e.g. req="version" -> matches "KOS.version"
                elif node_key.endswith(f".{req}"):
                    initial_nodes.add(node_key)

        stack = list(initial_nodes)
        
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            required_nodes.add(current)
            
            if current in self.nodes:
                # 把该节点的所有依赖加入堆栈
                for dep in self.nodes[current].dependencies:
                    if dep not in visited:
                        stack.append(dep)
        
        return required_nodes

    def get_execution_plan(self, required_vars: Optional[Set[str]] = None) -> List[Node]:
        """
        执行拓扑排序，返回按执行顺序排列的节点列表。
        支持按需加载：如果提供了 required_vars，只包含计算这些变量所需的节点。
        """
        # 1. 计算需要参与排序的节点子集
        relevant_keys = self._get_required_subgraph(required_vars)
        rich_debug(f"[Graph] 剪枝优化: 从 {len(self.nodes)} 个节点减少到 {len(relevant_keys)} 个")

        # 2. 构建排序器
        sorter = graphlib.TopologicalSorter()
        
        for key in relevant_keys:
            node = self.nodes[key]
            # 只添加也在 relevant_keys 中的依赖
            # 过滤掉不在子图中的外部依赖（如果有的话）
            deps = {d for d in node.dependencies if d in relevant_keys}
            sorter.add(key, *deps)

        try:
            sorted_keys = list(sorter.static_order())
        except graphlib.CycleError as e:
            cycle = " -> ".join(e.args[1])
            raise typer.BadParameter(f"检测到循环依赖: {cycle}")

        plan = []
        for key in sorted_keys:
            if key in self.nodes:
                plan.append(self.nodes[key])
        
        return plan