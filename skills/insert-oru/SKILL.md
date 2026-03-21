---
name: insert-oru
description: 将ORU插入到装配站。用于安装新ORU的最后一步。
tags: [oru, insert, assembly, 安装]
---

# 插入ORU技能

## 概述
此技能用于将机械臂持有的ORU插入到装配站的安装位置。

## 前置条件
1. 机械臂持有ORU (object_in_hand 不为空)
2. 装配站空闲 (assembly_station status: "ready")
3. 旧ORU已移除

## 执行步骤

### 步骤1: 确认持有ORU
```
使用 get_my_state 确认:
- gripper_closed: true
- object_in_hand: ORU ID
```

### 步骤2: 确认装配站状态
```
使用 get_object_info:
- object_id: "assembly_station"
确认状态为 "ready" 且没有其他ORU
```

### 步骤3: 移动到装配站上方
```
使用 move_to_object:
- object_id: "assembly_station"
- phase: "approach"
```

### 步骤4: 下降到安装位置
```
使用 move_to_object:
- object_id: "assembly_station"
- phase: "place"
```

### 步骤5: 水平插入
```
使用 move_relative:
- dx: 0.05 (向前移动5cm，插入ORU)
```

### 步骤6: 打开夹爪释放
```
使用 open_gripper
```

### 步骤7: 撤回机械臂
```
使用 move_relative:
- dz: 0.1 (向上撤回10cm)
```

## 成功标准
- ORU已插入装配站
- 机械臂夹爪已打开
- object_in_hand 为 null
- oru_new status: "installed"

## 错误处理
- 如果装配站被占用，等待或报告错误
- 如果插入受阻，检查对齐
- 如果ORU掉落，重新执行 pick-new-oru

## 后续操作
完成此技能后，应执行:
- pick-screwdriver: 抓取螺丝刀
- tighten-screw: 拧紧螺丝固定

## 示例调用
```json
{
  "skill": "insert-oru",
  "arm_id": "arm_right",
  "notes": "将新ORU插入装配站"
}
```
