---
name: loosen-screw
description: 使用螺丝刀拧松装配站上的螺丝。用于拆卸旧ORU前的准备操作。
tags: [screw, loosen, assembly, 拆卸]
---

# 拧松螺丝技能

## 概述
此技能用于使用螺丝刀拧松装配站上的螺丝，为拆卸旧ORU做准备。

## 前置条件
1. 机械臂持有螺丝刀 (object_in_hand: "screwdriver")
2. 旧ORU在装配站上 (oru_old status: "installed")
3. 机械臂可达装配站

## 执行步骤

### 步骤1: 确认持有螺丝刀
```
使用 get_my_state 确认:
- object_in_hand: "screwdriver"
```

### 步骤2: 确认ORU状态
```
使用 get_object_info:
- object_id: "oru_old"
确认状态为 "installed"
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

### 步骤5: 执行拧松操作
```
使用 toggle_screw:
- action: "loosen"
```

### 步骤6: 撤回
```
使用 move_relative:
- dz: 0.1 (向上撤回10cm)
```

## 成功标准
- 螺丝已拧松
- ORU可以被抓取和拔出
- oru_old status: "loose"

## 错误处理
- 如果没有螺丝刀，先执行 pick-screwdriver
- 如果螺丝锈死，报告错误
- 如果拧松失败，检查位置并重试

## 后续操作
完成此技能后，应执行:
- pick-old-oru: 抓取旧ORU
- 或将螺丝刀放回工具架

## 示例调用
```json
{
  "skill": "loosen-screw",
  "arm_id": "arm_left",
  "notes": "拧松螺丝准备拆卸旧ORU"
}
```
