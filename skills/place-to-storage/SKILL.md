---
name: place-to-storage
description: 将ORU放置到储物架。用于存放拆卸下来的旧ORU或临时存放新ORU。
tags: [oru, place, storage, 存放]
---

# 放置到储物架技能

## 概述
此技能用于将机械臂持有的ORU放置到储物架上。

## 前置条件
1. 机械臂持有ORU (object_in_hand 不为空)
2. 目标储物架空闲
3. 机械臂可达目标储物架

## 执行步骤

### 步骤1: 确认持有物体
```
使用 get_my_state 确认:
- gripper_closed: true
- object_in_hand: 物体ID
```

### 步骤2: 选择目标储物架
```
根据机械臂可达区域选择:
- arm_left 可达: storage_rack_left
- arm_right 可达: storage_rack_right

使用 get_object_info 检查储物架状态
```

### 步骤3: 移动到储物架上方
```
使用 move_to_object:
- object_id: "storage_rack_left" 或 "storage_rack_right"
- phase: "approach"
```

### 步骤4: 下降到放置位置
```
使用 move_to_object:
- object_id: 目标储物架ID
- phase: "place"
```

### 步骤5: 打开夹爪释放
```
使用 open_gripper
```

### 步骤6: 撤回机械臂
```
使用 move_relative:
- dz: 0.15 (向上撤回15cm)
```

## 成功标准
- ORU已放置在储物架上
- 机械臂夹爪已打开
- object_in_hand 为 null

## 错误处理
- 如果储物架被占用，选择另一个储物架
- 如果放置失败，重新调整位置
- 如果ORU掉落，执行 pick_object 重新抓取

## 后续操作
完成此技能后:
- move_home: 返回初始位置待命
- 或继续执行下一个任务

## 示例调用
```json
{
  "skill": "place-to-storage",
  "arm_id": "arm_left",
  "target": "storage_rack_left",
  "notes": "将旧ORU存放到左侧储物架"
}
```
