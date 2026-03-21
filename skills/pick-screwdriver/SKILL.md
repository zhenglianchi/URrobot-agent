---
name: pick-screwdriver
description: 从工具架抓取螺丝刀。用于需要螺丝操作的ORU更换任务。
tags: [tool, screwdriver, pick, 工具]
---

# 抓取螺丝刀技能

## 概述
此技能用于从工具架抓取螺丝刀，为后续的螺丝拧紧或拧松操作做准备。

## 前置条件
1. 螺丝刀在工具架上 (screwdriver status: "stored")
2. 机械臂空闲
3. 机械臂可达工具架

## 执行步骤

### 步骤1: 检查螺丝刀状态
```
使用 get_object_info:
- object_id: "screwdriver"
确认状态为 "stored"
```

### 步骤2: 检查机械臂可达性
```
使用 get_scene_state 确认:
- arm_left 或 arm_right 可达 tool_rack 区域
```

### 步骤3: 移动到螺丝刀上方
```
使用 move_to_object:
- object_id: "screwdriver"
- phase: "approach"
```

### 步骤4: 下降到抓取位置
```
使用 move_to_object:
- object_id: "screwdriver"
- phase: "grasp"
```

### 步骤5: 闭合夹爪抓取
```
使用 close_gripper:
- object_id: "screwdriver"
```

### 步骤6: 提升螺丝刀
```
使用 move_relative:
- dz: 0.1 (向上提升10cm)
```

## 成功标准
- 夹爪闭合，持有螺丝刀
- object_in_hand: "screwdriver"
- 螺丝刀已从工具架提升

## 错误处理
- 如果螺丝刀不在工具架，报告错误
- 如果机械臂不可达工具架，使用另一台机械臂
- 如果抓取失败，重新调整位置

## 后续操作
完成此技能后，可执行:
- loosen-screw: 拧松装配站螺丝
- tighten-screw: 拧紧装配站螺丝

## 示例调用
```json
{
  "skill": "pick-screwdriver",
  "arm_id": "arm_left",
  "notes": "抓取螺丝刀准备拆卸螺丝"
}
```
