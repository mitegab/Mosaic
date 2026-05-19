from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Any, Dict

FieldKind = Literal['string', 'number', 'boolean', 'date', 'datetime', 'json', 'relation', 'unknown']
RelationType = Literal['one-to-one', 'one-to-many', 'many-to-one', 'many-to-many']

class SchemaField(BaseModel):
    name: str
    type: str  # e.g., 'integer', 'character varying(255)', 'relation'
    kind: FieldKind
    primaryKey: Optional[bool] = None
    nullable: Optional[bool] = None
    relatedModel: Optional[str] = None
    relationType: Optional[RelationType] = None

class SchemaModel(BaseModel):
    name: str
    tableName: str
    description: Optional[str] = None
    rowEstimate: int
    fields: List[SchemaField]
    sampleRows: Optional[List[Dict[str, Any]]] = None
