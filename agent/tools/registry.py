"""
工具注册表模块

管理所有可用的工具，支持：
1. 动态注册工具
2. 按名称查找工具
3. 权限控制
4. 列出所有工具

类似依赖注入容器，但更轻量
"""

from typing import Callable, Dict, List, Optional


from .base_tool import BaseTool


class ToolRegistry:
    """
    工具注册表

    单例模式，确保全局只有一个注册表实例
    """

    _instance = None

    def __new__(cls):
        """单例模式实现"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化注册表"""
        if self._initialized:
            return

        self._tools: Dict[str, BaseTool] = {}  # 工具存储
        self._permissions: Dict[str, str] = {}  # 权限配置
        self._initialized = True

    def register(self, tool: BaseTool, required_role: str = "user"):
        """
        注册一个工具到注册表

        参数：
        - tool: 要注册的工具对象
        - required_role: 所需权限级别（user/admin等）

        示例：
        >>> registry = ToolRegistry()
        >>> tool = KnowledgeSearchTool()
        >>> registry.register(tool, required_role="user")
        """
        if tool.name in self._tools:
            raise ValueError(f"工具 '{tool.name}' 已经注册")

        self._tools[tool.name] = tool
        self._permissions[tool.name] = required_role

    def get_tool(self, name: str, user_role: str = "user") -> Optional[BaseTool]:
        """
        根据名称获取工具（带权限检查）

        参数：
        - name: 工具名称
        - user_role: 用户角色

        返回：
        - 工具对象，如果不存在或权限不足则返回None

        示例：
        >>> tool = registry.get_tool("knowledge_search", user_role="user")
        >>> if tool:
        ...     result = tool.execute(query="RAG")
        """
        # 检查工具是否存在
        if name not in self._tools:
            return None

        # 检查权限
        required_role = self._permissions.get(name, "user")
        if not self._check_permission(user_role, required_role):
            print(f"权限不足：需要 '{required_role}' 角色")
            return None

        return self._tools[name]

    def _check_permission(self, user_role: str, required_role: str) -> bool:
        """
        检查权限

        简化版：admin可以访问所有，user只能访问user级别的工具

        生产环境可以用RBAC（基于角色的访问控制）
        """
        if user_role == "admin":
            return True

        if user_role == required_role:
            return True

        # user不能访问admin工具
        if required_role == "admin":
            return False

        return True

    def list_tools(self, user_role: str = "user") -> List[Dict]:
        """
        列出所有可用工具（根据权限过滤）

        参数：
        - user_role: 用户角色

        返回：
        - 工具信息列表

        示例：
        >>> tools = registry.list_tools("user")
        >>> for tool in tools:
        ...     print(f"{tool['name']}: {tool['description']}")
        """
        available_tools = []

        for name, tool in self._tools.items():
            required_role = self._permissions.get(name, "user")

            if self._check_permission(user_role, required_role):
                available_tools.append({
                    "name": tool.name,
                    "description": tool.description
                })

        return available_tools

    def get_all_tools(self):
        """
        获取所有工具，转换为 LangChain 兼容格式

        create_agent 需要 langchain_core.tools.BaseTool 类型，
        自动将自定义的 BaseTool 转换为 StructuredTool
        """
        from langchain_core.tools import StructuredTool

        lc_tools = []
        for name, tool in self._tools.items():
            if hasattr(tool, 'execute'):
                # 自定义 BaseTool → 包装为 LangChain StructuredTool
                # 核心修复：用默认参数立即绑定 t 和 tool
                def make_wrapper(tool_obj, tool_name):
                    def wrapper(input_dict: dict = None, **kwargs):
                        # 兼容 LangChain 传入字典作为第一个参数
                        if input_dict is None and kwargs:
                            input_dict = kwargs
                        elif input_dict is None:
                            input_dict = {}

                        result = tool_obj.execute(**input_dict)

                        if hasattr(result, 'to_string'):
                            return result.to_string()
                        return str(result)
                    wrapper.__name__ = tool_name
                    wrapper.__doc__ = tool.description
                    return wrapper

                lc_tool = StructuredTool.from_function(
                    func=make_wrapper(tool,name),
                    name=tool.name,
                    description=tool.description,
                )
                lc_tools.append(lc_tool)
            else:
                # 已经是 LangChain 工具（如 @tool 装饰器创建的）
                lc_tools.append(tool)

        return lc_tools
    def unregister(self, name: str):
        """
        注销工具（用于测试或动态卸载）

        参数：
        - name: 工具名称
        """
        if name in self._tools:
            del self._tools[name]
            del self._permissions[name]

    def clear(self):
        """清空所有工具（用于测试）"""
        self._tools.clear()
        self._permissions.clear()

    def __len__(self):
        """返回工具数量"""
        return len(self._tools)

    def __contains__(self, name: str):
        """检查工具是否已注册"""
        return name in self._tools


# 创建全局注册表实例
registry = ToolRegistry()
