---
name: tighten-screw
description: 使用螺丝刀拧紧装配站上的螺丝。用于安装新ORU后的固定操作。
tags: [screw, tighten, assembly, 安装]
---

# 拧紧螺丝技能

## 概述
此技能用于使用螺丝刀拧紧装配站上的螺丝，完成ORU的固定安装。

## 前置条件
1. 机械臂持有螺丝刀 (object_in_hand: "screwdriver")
2. 新ORU已放置在装配站上
3. 机械臂可达装配站

## 执行步骤

### 步骤1: 确认持有螺丝刀
```
使用 get_my_state 确认:
- object_in_hand: "screwdriver"
```

### 步骤2: 确认ORU已放置
```
使用 get_object_info:
- object_id: "oru_new"
确认状态为 "placed" 或 "installed"
```

### 步骤3: 移动到装配站上方
```
使用 move_to_object:
- object_id: "assembly_station"
- phase: "approach"
```

### 步骤4: 移动到螺丝位置
```
使用 move_to_object:
- object_id: "assembly_station"
- phase: "grasp"
```

### 步骤5: 执行拧紧操作
```
使用 toggle_screw:
- action: "tighten"
```

### 步骤6: 撤回
```
使用 move_relative:
- dz: 0.1 (向上撤回10cm)
```

## 成功标准
- 螺丝已拧紧
- ORU牢固固定在装配站上
- assembly_station status: "secured"

## 错误处理
- 如果没有螺丝刀，先执行 pick-screwdriver
- 如果螺丝滑丝，报告错误
- 如果拧紧失败，检查位置并重试

## 后续操作
完成此技能后，应执行:
- place-to-storage: 将螺丝刀放回工具架
- move_home: 返回初始位置

## 示例调用
```json
{
  "skill": "tighten-screw",
  "arm_id": "arm_left",
  "notes": "拧紧螺丝固定新ORU"
}
```
