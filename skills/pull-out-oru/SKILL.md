---
name: pull-out-oru
description: 将ORU从装配站完全拔出。在抓取旧ORU后使用此技能将其从装配站分离。
tags: [oru, pull, assembly, 拆卸]
---

# 拔出ORU技能

## 概述
此技能用于将已抓取的ORU从装配站完全拔出。执行此技能前，必须已经抓取了ORU。

## 前置条件
1. 机械臂已抓取ORU (object_in_hand 不为空)
2. ORU已从装配站略微提升
3. 装配站螺丝已拧松

## 执行步骤

### 步骤1: 确认抓取状态
```
使用 get_my_state 确认:
- gripper_closed: true
- object_in_hand: "oru_old" 或其他ORU ID
```

### 步骤2: 水平移动拔出
```
使用 move_relative:
- dx: -0.1 (向后移动10cm，从装配站拔出)
- dy: 0
- dz: 0
```

### 步骤3: 继续提升
```
使用 move_relative:
- dz: 0.1 (再提升10cm，确保完全脱离)
```

### 步骤4: 确认脱离
```
使用 get_object_info:
- object_id: "assembly_station"
确认 ORU 不再在装配站上
```

## 成功标准
- ORU已完全脱离装配站
- 机械臂稳定持有ORU
- ORU位置已离开装配站区域

## 错误处理
- 如果拔出受阻，检查是否有其他固定装置
- 如果ORU掉落，重新执行 pick-old-oru
- 如果碰撞风险，请求协调

## 后续操作
完成此技能后，应执行:
- place-to-storage: 将ORU放置到储物架

## 示例调用
```json
{
  "skill": "pull-out-oru",
  "arm_id": "arm_left",
  "notes": "将旧ORU从装配站完全拔出"
}
```
