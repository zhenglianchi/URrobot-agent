---
name: pick-old-oru
description: 从装配站抓取旧的ORU（轨道更换单元）。适用于拆卸旧ORU的第一步。
tags: [oru, pick, assembly,拆卸]
---

# 抓取旧ORU技能

## 概述
此技能用于从装配站抓取旧的ORU单元。在执行此技能前，必须确保装配站上的螺丝已经拧松。

## 前置条件
1. 装配站上的螺丝已经拧松（使用 loosen-screw 技能）
2. 机械臂空闲且可达装配站
3. 夹爪已打开

## 执行步骤

### 步骤1: 检查状态
```
使用 get_scene_state 确认:
- oru_old 的状态为 "installed" 或 "loose"
- 机械臂空闲
```

### 步骤2: 移动到ORU上方
```
使用 move_to_object:
- object_id: "oru_old"
- phase: "approach"
```

### 步骤3: 下降到抓取位置
```
使用 move_to_object:
- object_id: "oru_old"
- phase: "grasp"
```

### 步骤4: 闭合夹爪抓取
```
使用 close_gripper:
- object_id: "oru_old"
```

### 步骤5: 提升ORU
```
使用 move_relative:
- dz: 0.15 (向上提升15cm)
```

## 成功标准
- 夹爪闭合，持有 oru_old
- ORU已从装配站提升
- 机械臂状态显示 object_in_hand: "oru_old"

## 错误处理
- 如果ORU状态不是 "loose"，先执行 loosen-screw
- 如果机械臂繁忙，等待或使用另一台机械臂
- 如果抓取失败，检查位置并重试

## 后续操作
完成此技能后，应执行:
- pull-out-oru: 将ORU完全拔出
- place-to-storage: 放置到储物架

## 示例调用
```json
{
  "skill": "pick-old-oru",
  "arm_id": "arm_left",
  "notes": "拆卸旧ORU的第一步"
}
```
