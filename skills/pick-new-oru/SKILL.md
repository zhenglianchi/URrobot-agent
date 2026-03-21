---
name: pick-new-oru
description: 从储物架抓取新的ORU。用于安装新ORU的第一步。
tags: [oru, pick, storage, 安装]
---

# 抓取新ORU技能

## 概述
此技能用于从储物架抓取新的ORU，准备安装到装配站。

## 前置条件
1. 新ORU在储物架上 (oru_new status: "stored")
2. 机械臂空闲
3. 机械臂可达储物架

## 执行步骤

### 步骤1: 检查新ORU状态
```
使用 get_object_info:
- object_id: "oru_new"
确认状态为 "stored" 和位置
```

### 步骤2: 选择可达储物架
```
根据ORU位置确认:
- 如果在 storage_rack_left，使用 arm_left
- 如果在 storage_rack_right，使用 arm_right
```

### 步骤3: 移动到ORU上方
```
使用 move_to_object:
- object_id: "oru_new"
- phase: "approach"
```

### 步骤4: 下降到抓取位置
```
使用 move_to_object:
- object_id: "oru_new"
- phase: "grasp"
```

### 步骤5: 闭合夹爪抓取
```
使用 close_gripper:
- object_id: "oru_new"
```

### 步骤6: 提升ORU
```
使用 move_relative:
- dz: 0.15 (向上提升15cm)
```

## 成功标准
- 夹爪闭合，持有新ORU
- object_in_hand: "oru_new"
- ORU已从储物架提升

## 错误处理
- 如果新ORU不在储物架，报告错误
- 如果机械臂不可达，使用另一台机械臂
- 如果抓取失败，重新调整位置

## 后续操作
完成此技能后，应执行:
- insert-oru: 将ORU插入装配站

## 示例调用
```json
{
  "skill": "pick-new-oru",
  "arm_id": "arm_right",
  "notes": "从储物架抓取新ORU准备安装"
}
```
