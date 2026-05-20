from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Any, Dict, Union

FieldKind = Literal['string', 'number', 'boolean', 'date', 'datetime', 'json', 'relation', 'unknown']
RelationType = Literal['one-to-one', 'one-to-many', 'many-to-one', 'many-to-many']

class SchemaField(BaseModel):
    name: str
    type: str  # e.g., 'integer', 'character varying(255)', 'relation'
    kind: FieldKind
    primaryKey: Optional[bool] = None
    nullable: Optional[bool] = None
    unique: Optional[bool] = None
    indexed: Optional[bool] = None
    relatedModel: Optional[str] = None
    relationType: Optional[RelationType] = None
    constraints: Optional[List[str]] = None
    sampleValues: Optional[List[Any]] = None
    description: Optional[str] = None

class SchemaModel(BaseModel):
    name: str
    tableName: str
    description: Optional[str] = None
    rowEstimate: int
    fields: List[SchemaField]
    sampleRows: Optional[List[Dict[str, Any]]] = None

class QueryFilter(BaseModel):
    field: str
    operator: str  # e.g., 'exact', 'icontains', 'gt', 'in', 'isnull'
    value: Any
    logic: Optional[Literal['AND', 'OR', 'and', 'or']] = None

class QueryFilterGroup(BaseModel):
    logic: Literal['and', 'or', 'AND', 'OR'] = 'and'
    filters: List[Union[QueryFilter, 'QueryFilterGroup']]

class QueryRelation(BaseModel):
    relation: Optional[str] = None
    select: Optional[List[str]] = None
    filters: Optional[List[Union[QueryFilter, QueryFilterGroup]]] = None
    relations: Optional[List['QueryRelation']] = None
    
    # Frontend format support
    from_: Optional[str] = Field(None, alias="from")
    to: Optional[str] = None
    field: Optional[str] = None

    class Config:
        populate_by_name = True

class QueryDsl(BaseModel):
    model: str
    select: Optional[List[str]] = None
    output: Optional[List[str]] = None
    filters: Optional[List[Union[QueryFilter, QueryFilterGroup]]] = None
    relations: Optional[List[QueryRelation]] = None
    orderBy: Optional[List[str]] = None
    limit: Optional[int] = Field(None, ge=1, le=10000)  # matching frontend max of 10000
    offset: Optional[int] = Field(None, ge=0)
    groups: Optional[List['QueryDsl']] = None

# Rebuild recursive models in Pydantic v2
QueryFilterGroup.model_rebuild()
QueryRelation.model_rebuild()
QueryDsl.model_rebuild()
