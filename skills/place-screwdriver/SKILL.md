---
name: place-screwdriver
description: 将螺丝刀放回工具架原位。螺丝操作完成后归还工具。
tags: [tool, screwdriver, place, storage, 工具]
---

# 放回螺丝刀技能

## 概述
此技能用于将螺丝刀放回工具架原位，完成工具归位。在所有螺丝操作完成后执行。

## 前置条件
1. 螺丝刀被机械臂持有 (screwdriver held_by: [arm_id])
2. 工具架在位
3. 机械臂空闲且可达工具架

## 执行步骤

### 步骤1: 检查状态
```
使用 get_object_info:
- object_id: "screwdriver"
确认被当前机械臂持有
```

### 步骤2: 移动到工具架上方接近位置
```
使用 move_to_object:
- object_id: "screwdriver" (工具架上的原位)
- phase: "approach"
```

### 步骤3: 下降到放置位置
```
使用 move_to_object:
- object_id: "screwdriver"
- phase: "place"
```

### 步骤4: 打开夹爪释放
```
使用 open_gripper
```

### 步骤5: 提升机械臂
```
使用 move_relative:
- dz: 0.1 (向上提升10cm，离开螺丝刀)
```

### 步骤6: 更新物体状态
```
使用 update_object_state:
- object_id: "screwdriver"
- status: "stored"
- held_by: null
```

## 成功标准
- 夹爪打开，不再持有螺丝刀
- 螺丝刀位于工具架原位，状态为 "stored"
- 机械臂空闲

## 错误处理
- 如果螺丝刀不被当前机械臂持有，报告错误
- 如果到达位置偏差过大，重新调整位置

## 前置技能
- loosen-screw 或 tighten-screw 已完成

## 示例调用
```json
{
  "skill": "place-screwdriver",
  "arm_id": "arm_left",
  "notes": "螺丝操作完成，将螺丝刀放回工具架"
}
```
