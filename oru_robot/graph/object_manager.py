
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import json
from enum import Enum


class ObjectType(Enum):
    ORU = "oru"
    STORAGE_RACK = "storage_rack"
    SCREWDRIVER = "screwdriver"
    TOOL_RACK = "tool_rack"
    ASSEMBLY_STATION = "assembly_station"
    PICK_POINT = "pick_point"


class RelationType(Enum):
    CONTAINS = "contains"
    PLACED_AT = "placed_at"
    ATTACHED_TO = "attached_to"
    NEAR = "near"
    TARGET_FOR = "target_for"


@dataclass
class ObjectPosition:
    x: float
    y: float
    z: float
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0
    frame_id: str = "base"

    def to_list(self):
        return [self.x, self.y, self.z, self.rx, self.ry, self.rz]

    @classmethod
    def from_list(cls, pose, frame_id="base"):
        return cls(
            x=pose[0], y=pose[1], z=pose[2],
            rx=pose[3] if len(pose) > 3 else 0.0,
            ry=pose[4] if len(pose) > 4 else 0.0,
            rz=pose[5] if len(pose) > 5 else 0.0,
            frame_id=frame_id
        )


@dataclass
class ObjectRelation:
    source_id: str
    target_id: str
    relation_type: RelationType
    metadata: Dict = field(default_factory=dict)


@dataclass
class PhysicalObject:
    object_id: str
    object_type: ObjectType
    position: ObjectPosition
    relations: List[ObjectRelation] = field(default_factory=list)
    properties: Dict = field(default_factory=dict)
    is_available: bool = True


class ObjectGraph:
    def __init__(self):
        self.objects: Dict[str, PhysicalObject] = {}
        self.relations: List[ObjectRelation] = []

    def add_object(self, obj):
        self.objects[obj.object_id] = obj

    def remove_object(self, object_id):
        if object_id in self.objects:
            del self.objects[object_id]
            self.relations = [
                r for r in self.relations
                if r.source_id != object_id and r.target_id != object_id
            ]

    def add_relation(self, relation):
        self.relations.append(relation)
        if relation.source_id in self.objects:
            self.objects[relation.source_id].relations.append(relation)

    def get_object(self, object_id):
        return self.objects.get(object_id)

    def get_objects_by_type(self, object_type):
        return [obj for obj in self.objects.values() if obj.object_type == object_type]

    def get_related_objects(
        self, 
        object_id: str, 
        relation_type: Optional[RelationType] = None
    ) -> List[PhysicalObject]:
        related = []
        for relation in self.relations:
            if relation.source_id == object_id:
                if relation_type is None or relation.relation_type == relation_type:
                    target_obj = self.objects.get(relation.target_id)
                    if target_obj:
                        related.append(target_obj)
        return related

    def update_position(self, object_id, new_position):
        if object_id in self.objects:
            self.objects[object_id].position = new_position
            return True
        return False

    def get_oru_pick_position(self, oru_id):
        oru = self.get_object(oru_id)
        if not oru:
            return None
        
        pick_points = self.get_related_objects(oru_id, RelationType.TARGET_FOR)
        if pick_points:
            return pick_points[0].position
        
        return oru.position

    def get_storage_rack_position(self, storage_rack_id, slot_id=None):
        rack = self.get_object(storage_rack_id)
        if not rack:
            return None
        
        if slot_id:
            for relation in rack.relations:
                if relation.relation_type == RelationType.CONTAINS:
                    slot = self.get_object(relation.target_id)
                    if slot and slot.object_id == slot_id:
                        return slot.position
        
        return rack.position

    def save_to_file(self, filepath):
        data = {
            "objects": [
                {
                    "object_id": obj.object_id,
                    "object_type": obj.object_type.value,
                    "position": {
                        "x": obj.position.x,
                        "y": obj.position.y,
                        "z": obj.position.z,
                        "rx": obj.position.rx,
                        "ry": obj.position.ry,
                        "rz": obj.position.rz,
                        "frame_id": obj.position.frame_id
                    },
                    "properties": obj.properties,
                    "is_available": obj.is_available
                }
                for obj in self.objects.values()
            ],
            "relations": [
                {
                    "source_id": r.source_id,
                    "target_id": r.target_id,
                    "relation_type": r.relation_type.value,
                    "metadata": r.metadata
                }
                for r in self.relations
            ]
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_from_file(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.objects = {}
        self.relations = []
        
        for obj_data in data["objects"]:
            pos = ObjectPosition(
                x=obj_data["position"]["x"],
                y=obj_data["position"]["y"],
                z=obj_data["position"]["z"],
                rx=obj_data["position"]["rx"],
                ry=obj_data["position"]["ry"],
                rz=obj_data["position"]["rz"],
                frame_id=obj_data["position"]["frame_id"]
            )
            obj = PhysicalObject(
                object_id=obj_data["object_id"],
                object_type=ObjectType(obj_data["object_type"]),
                position=pos,
                properties=obj_data["properties"],
                is_available=obj_data["is_available"]
            )
            self.add_object(obj)
        
        for rel_data in data["relations"]:
            rel = ObjectRelation(
                source_id=rel_data["source_id"],
                target_id=rel_data["target_id"],
                relation_type=RelationType(rel_data["relation_type"]),
                metadata=rel_data["metadata"]
            )
            self.add_relation(rel)

    def visualize(self):
        result = ["=== Object Graph ===", ""]
        for obj_id, obj in self.objects.items():
            result.append(f"[{obj.object_type.value}] {obj_id}")
            result.append(f"  Position: {obj.position.to_list()}")
            if obj.relations:
                result.append("  Relations:")
                for rel in obj.relations:
                    result.append(f"    - {rel.relation_type.value} -&gt; {rel.target_id}")
            result.append("")
        return "\n".join(result)

