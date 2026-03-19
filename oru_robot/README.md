
# ORU更换机器人系统

基于 LangGraph + RAG + Skills 的智能机器人ORU更换系统

---

## 📋 项目概述

本项目实现了一个完整的ORU（Optical Receiver Unit）更换机器人系统，包含以下核心功能：

1. **Skills 技能系统** - 9个标准化的机器人操作技能
2. **物体关系与位置管理** - Graph中记录物体关系和位置
3. **LangGraph 工作流编排** - 完整的ORU更换流程自动化
4. **RAG API查询** - 从API文档中智能检索相关接口

---

## 📁 项目结构

```
python-langgraph/
├── oru_robot/                    # ORU机器人系统
│   ├── __init__.py              # 包导出
│   ├── main.py                  # 主入口程序
│   ├── README.md                # 本文档
│   │
│   ├── graph/                   # 核心工作流模块
│   │   ├── object_manager.py    # 物体关系与位置管理（核心！）
│   │   ├── state.py             # 状态定义（TypedDict）
│   │   └── oru_workflow.py      # LangGraph ORU更换工作流
│   │
│   ├── models/                  # 模型管理
│   │   └── model_factory.py     # 通义千问模型工厂
│   │
│   ├── rag/                     # RAG服务模块
│   │   └── api_rag_service.py   # API文档RAG查询服务
│   │
│   ├── skills/                  # 技能定义（Markdown）
│   │   ├── SK001_MoveToORUPickPoint.md
│   │   ├── SK002_PullOutORU.md
│   │   ├── SK003_MoveToStorageRack.md
│   │   ├── SK004_PickNewORU.md
│   │   ├── SK005_MoveToAssemblyPosition.md
│   │   ├── SK006_InsertORU.md
│   │   ├── SK007_PickScrewdriver.md
│   │   ├── SK008_TightenScrews.md
│   │   └── SK009_PlaceScrewdriver.md
│   │
│   └── data/
│       ├── knowledge_base/      # RAG向量库存储
│       └── object_positions/    # 物体位置配置
│           └── example_setup.json
│
├── utils/                        # 工具函数（保留）
├── UR_Base.py                   # UR机器人底层控制（保留）
├── API_Reference_Control.pdf    # API文档（保留）
└── API_Reference_Receive.pdf    # API文档（保留）
```

---

## 🎯 核心功能详解

---

### 1. 物体关系与位置管理 (`graph/object_manager.py`)

**核心功能**：管理所有物理对象及其位置和关系

#### 支持的物体类型
| 类型 | 说明 |
|------|------|
| `ORU` | 待更换的ORU单元 |
| `STORAGE_RACK` | 收纳架 |
| `SCREWDRIVER` | 螺丝刀工具 |
| `TOOL_RACK` | 工具架 |
| `ASSEMBLY_STATION` | 装配工位 |
| `PICK_POINT` | 抓取点 |

#### 支持的关系类型
| 关系类型 | 说明 | 示例 |
|----------|------|------|
| `CONTAINS` | 包含 | 收纳架包含槽位 |
| `PLACED_AT` | 放置在 | ORU放置在收纳架上 |
| `ATTACHED_TO` | 附着于 | 螺丝刀附着在工具架 |
| `NEAR` | 邻近 | 装配工位邻近收纳架 |
| `TARGET_FOR` | 目标对象 | 抓取点是ORU的抓取目标 |

#### 核心类
- **`ObjectPosition`**：6D位置（x, y, z, rx, ry, rz）
- **`ObjectRelation`**：物体之间的关系
- **`PhysicalObject`**：物理对象（含位置、关系、属性）
- **`ObjectGraph`**：物体图管理器

#### 主要方法
```python
object_graph = ObjectGraph()

# 添加物体
object_graph.add_object(obj)

# 添加关系
object_graph.add_relation(relation)

# 查询物体
object_graph.get_object("oru_001")
object_graph.get_objects_by_type(ObjectType.ORU)
object_graph.get_related_objects("oru_001", RelationType.TARGET_FOR)

# 位置管理
object_graph.update_position("oru_001", new_position)
object_graph.get_oru_pick_position("oru_001")
object_graph.get_storage_rack_position("rack_001", "slot_1")

# 持久化
object_graph.save_to_file("config.json")
object_graph.load_from_file("config.json")

# 可视化
print(object_graph.visualize())
```

---

### 2. 9个Skills 技能定义 (`skills/`)

| SK ID | 技能名称 | 功能描述 |
|-------|----------|----------|
| **SK001** | `MoveToORUPickPoint` | 移动到ORU抓取点，收拢夹爪抓取ORU |
| **SK002** | `PullOutORU` | 向上移动拔出ORU |
| **SK003** | `MoveToStorageRack` | 移动到收纳架，松开夹爪放置ORU |
| **SK004** | `PickNewORU` | 抓取新的ORU |
| **SK005** | `MoveToAssemblyPosition` | 移动到装配位置 |
| **SK006** | `InsertORU` | 进行装配插入（带力控） |
| **SK007** | `PickScrewdriver` | 抓取螺丝刀工具 |
| **SK008** | `TightenScrews` | 依次旋拧ORU螺丝 |
| **SK009** | `PlaceScrewdriver` | 放置螺丝刀工具 |

每个Skill包含：
- 功能描述
- 输入输出参数
- 执行步骤
- 前置/后置条件
- 错误处理

---

### 3. LangGraph 工作流编排 (`graph/oru_workflow.py`)

#### ORU更换完整流程
```
[初始化]
    ↓
[SK001] 移动到ORU抓取点 → 抓取ORU
    ↓
[SK002] 向上移动 → 拔出ORU
    ↓
[SK003] 移动到收纳架 → 放置旧ORU
    ↓
[SK004] 抓取新ORU
    ↓
[SK005] 移动到装配位置
    ↓
[SK006] 装配插入ORU
    ↓
[SK007] 抓取螺丝刀
    ↓
[SK008] 依次旋拧螺丝
    ↓
[SK009] 放置螺丝刀
    ↓
[完成检查]
```

#### 状态定义 (`state.py`)
使用 `TypedDict` 定义完整状态：
- `current_step_index` - 当前步骤索引
- `oru_old_id` / `oru_new_id` - 新旧ORU ID
- `oru_picked` / `oru_installed` - ORU状态
- `tool_in_hand` - 手中工具
- `screws_tightened` - 已拧紧螺丝数
- `errors` / `warnings` - 错误和警告
- `execution_log` - 执行日志
- `object_graph` - 物体图引用

---

### 4. RAG API查询系统 (`rag/api_rag_service.py`)

**功能**：从API文档中智能检索相关接口

#### 支持的文档
- `API_Reference_Control.pdf` - 控制接口文档
- `API_Reference_Receive.pdf` - 接收接口文档

#### 核心功能
1. **PDF加载**：自动加载并分割PDF文档
2. **向量化**：使用通义千问嵌入模型
3. **向量检索**：Chroma向量库Top-K检索
4. **大模型总结**：结合检索结果生成回答

#### 使用示例
```python
from oru_robot import APIRAGService

rag_service = APIRAGService()

# 加载API文档
rag_service.load_pdf_documents([
    "API_Reference_Control.pdf",
    "API_Reference_Receive.pdf"
])

# 自然语言查询
answer = rag_service.query("如何设置数字输出？")
print(answer)

answer = rag_service.query("moveL函数的参数说明")
print(answer)
```

---

## 🚀 快速开始

### 1. 配置物体位置

编辑 `oru_robot/data/object_positions/example_setup.json`，配置实际的物体位置和关系。

### 2. 放置API文档

将 `API_Reference_Control.pdf` 和 `API_Reference_Receive.pdf` 放在项目根目录。

### 3. 运行系统

方式一：使用Python API
```python
from oru_robot import (
    ObjectGraph,
    ORUReplacementWorkflow,
    create_initial_state
)

# 初始化物体图
object_graph = ObjectGraph()
object_graph.load_from_file("oru_robot/data/object_positions/example_setup.json")

# 查看物体图
print(object_graph.visualize())

# 创建工作流
workflow = ORUReplacementWorkflow(object_graph)

# 运行
initial_state = create_initial_state(
    oru_old_id="oru_old_001",
    oru_new_id="oru_new_001",
    storage_rack_id="storage_rack_001",
    assembly_station_id="assembly_station_001",
    tool_rack_id="tool_rack_001",
    screwdriver_id="screwdriver_001",
    total_screws=4
)

final_state = workflow.run(initial_state)
```

方式二：直接运行主程序
```bash
cd python-langgraph
python -m oru_robot.main
```

---

## 🔧 后续开发计划

1. **Skills实现**：填充Markdown文件中的具体实现细节
2. **机器人集成**：连接真实的UR机器人（UR_Base.py）
3. **Agent增强**：添加任务规划、故障处理、RAG查询等Agent
4. **可视化**：添加工作流和物体位置的可视化界面
5. **测试**：添加单元测试和集成测试

---

## 📝 注意事项

- 所有类型注解已移除，代码更简洁
- `@dataclass` 和 `TypedDict` 的字段类型保留（这些是必需的）
- 旧的扫地机器人项目文件已清理

