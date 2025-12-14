from typing import Any, Dict, Set, Optional

class DependencyTracker:
    def __init__(self):
        self.accessed_paths: Set[str] = set()

class MagicDummy:
    """
    一个可以响应任意属性和索引访问的虚拟对象。
    用于在依赖追踪阶段替代不存在的值或复杂对象。
    """
    def __init__(self, path: str, tracker: DependencyTracker):
        self._path = path
        self._tracker = tracker
    
    def __getattr__(self, name: str):
        new_path = f"{self._path}.{name}"
        self._tracker.accessed_paths.add(new_path)
        return MagicDummy(new_path, self._tracker)
    
    def __getitem__(self, key: Any):
        new_path = f"{self._path}.{key}"
        self._tracker.accessed_paths.add(new_path)
        return MagicDummy(new_path, self._tracker)

    def __str__(self):
        return f"__DUMMY_{self._path}__"
    
    def __iter__(self):
        # 允许迭代，防止 {% for i in var %} 报错
        return iter([])

    def __bool__(self):
        # 默认为 False，防止影响控制流太深
        return False

class TrackingDict(dict):
    """
    一个包装字典，用于记录所有被访问过的键路径。
    """
    def __init__(self, data: Dict[str, Any] = None, prefix: str = "", tracker: Optional[DependencyTracker] = None):
        self._prefix = prefix
        self._tracker = tracker
        if data:
            for k, v in data.items():
                if isinstance(v, dict):
                    # 递归封装子字典
                    new_prefix = f"{prefix}.{k}" if prefix else k
                    self[k] = TrackingDict(v, new_prefix, tracker)
                else:
                    self[k] = v

    def __getitem__(self, key: str):
        full_path = f"{self._prefix}.{key}" if self._prefix else key
        
        # 1. 记录访问
        if self._tracker:
            self._tracker.accessed_paths.add(full_path)
        
        # 2. 返回值处理
        if key in self:
            val = super().__getitem__(key)
            if isinstance(val, TrackingDict):
                return val
            
            # 如果是动态指令字符串（以 $ 开头），返回 Dummy 防止 Jinja 尝试解析或渲染它
            # 同时也防止副作用（虽然 Dry Run 不应该有副作用，但以防万一）
            if isinstance(val, str) and val.startswith('$'):
                return MagicDummy(full_path, self._tracker)
            
            return val
        else:
            # 键不存在时，返回 MagicDummy 以支持链式访问 (e.g., {{ a.b.c }} where a exists but b doesn't)
            return MagicDummy(full_path, self._tracker)

def create_tracking_context(raw_context: Dict[str, Any]) -> tuple[Dict[str, Any], DependencyTracker]:
    """
    从原始上下文创建一个追踪上下文和一个追踪器。
    """
    tracker = DependencyTracker()
    tracking_context = TrackingDict(raw_context, prefix="", tracker=tracker)
    return tracking_context, tracker