# 多人共享记账系统（实验三 · 软件实现与构建）

由实验二 UML 设计落地而来的可运行实现。分层结构与实验二组件图一一对应，
代码风格遵循 PEP 8 并通过 pylint 10.00/10 检测。

## 运行环境

- Python 3.12（标准库即可运行，无需第三方依赖）
- 图形界面使用标准库 `tkinter`，Windows / macOS / Linux 的官方 Python 均自带
- 数据库使用标准库 `sqlite3`，数据文件为单个 `.db` 文件

## 目录结构

```
源代码/
├── shared_ledger/          应用代码
│   ├── domain/             领域层：15 个实体 + 8 个枚举 + 异常体系
│   ├── support/            支撑层：金额分摊 / 状态机 / 幂等 / 乐观锁
│   ├── persistence/        数据层：SQLite 表结构 + 各实体仓储
│   ├── service/            业务层：9 个业务服务 + 权限守卫
│   ├── ui/                 表现层：tkinter 桌面界面
│   ├── app.py              装配根：组装数据库与全部服务
│   ├── cli.py              命令行入口
│   └── demo.py             端到端演示剧本（同时是界面种子数据）
├── tests/                  unittest 单元测试
├── tools/code_stats.py     代码规模统计脚本
├── .pylintrc               pylint 代码风格配置
└── requirements.txt        运行依赖（仅标准库，留空以示说明）
```

## 运行

```bash
# 端到端演示场景：依次演出 21 个业务场景并打印每一步结果
python -m shared_ledger.cli demo

# 启动桌面界面（首次启动自动灌入演示数据）
python -m shared_ledger.cli ui --db shared_ledger.db

# 显示版本号
python -m shared_ledger.cli version
```

演示账号：`zhoucy` / `jiangzc` / `chenmo`，口令统一为 `123456`；
角色分别为管理员、记账成员、只读成员。

## 测试

```bash
python -m unittest discover -s tests -v
```

## 代码风格检测

```bash
python -m pylint shared_ledger
```

配置见 `.pylintrc`，每一条放宽的规则都写明了放宽原因。

## 代码规模统计

```bash
python tools/code_stats.py --root .
```
