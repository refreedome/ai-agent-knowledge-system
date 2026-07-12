"""
工具基类模块

定义工具的标准接口，所有工具都必须继承这个基类。

好处：
1. 统一接口 - 所有工具都有相同的结构
2. 类型安全 - IDE可以自动补全和检查
3. 便于扩展 - 可以在基类中添加通用功能（如日志、监控）
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseTool(ABC):
    """
    工具基类（抽象类）

    所有自定义工具都应该继承这个类并实现必要的方法
    """

    def __init__(self, name: str, description: str):
        """
        初始化工具

        参数：
        - name: 工具名称（唯一标识）
        - description: 工具描述（告诉Agent什么时候用这个工具）
        """
        self.name = name
        self.description = description

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """
        执行工具的核心逻辑（必须由子类实现）

        参数：
        - **kwargs: 工具所需的参数

        返回：
        - 工具执行结果
        """
        pass

    def validate_params(self, **kwargs) -> bool:
        """
        验证参数是否合法（可选重写）

        参数：
        - **kwargs: 要验证的参数

        返回：
        - True表示参数合法，False表示不合法
        """
        return True

    def to_dict(self) -> Dict:
        """
        将工具信息转换为字典（用于序列化）

        返回：
        - 包含工具信息的字典
        """
        return {
            "name": self.name,
            "description": self.description
        }

    def __repr__(self):
        return f"BaseTool(name='{self.name}', description='{self.description}')"


class ToolResult:
    """
    工具执行结果封装类

    统一工具返回的格式，包含成功/失败状态
    """

    def __init__(self, success: bool, data: Any = None, error: str = None):
        """
        初始化结果对象

        参数：
        - success: 是否成功
        - data: 成功时的数据
        - error: 失败时的错误信息
        """
        self.success = success
        self.data = data
        self.error = error

    def to_string(self) -> str:
        """转换为字符串（给Agent看的结果）"""
        if self.success:
            return str(self.data)
        else:
            return f"工具执行失败: {self.error}"

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error
        }

    @staticmethod
    def ok(data: Any) -> 'ToolResult':
        """创建成功结果"""
        return ToolResult(success=True, data=data)

    @staticmethod
    def fail(error: str) -> 'ToolResult':
        """创建失败结果"""
        return ToolResult(success=False, error=error)
