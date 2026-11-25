"""多人共享记账系统 —— 多人共享记账系统的 Python 实现。

分层结构与实验二的 UML 组件图保持一致：

- ``domain``：领域层，实体与枚举；
- ``support``：支撑层，金额分摊、状态机、幂等与乐观锁；
- ``persistence``：数据层，SQLite 表结构与仓储；
- ``service``：业务层，九个业务服务；
- ``ui``：表现层，tkinter 桌面界面。
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
