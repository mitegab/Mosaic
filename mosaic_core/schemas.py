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
    relatedModel: Optional[str] = None
    relationType: Optional[RelationType] = None

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


class QueryFilterGroup(BaseModel):
    logic: Literal['and', 'or'] = 'and'
    filters: List[Union[QueryFilter, 'QueryFilterGroup']]


class QueryRelation(BaseModel):
    relation: str
    select: Optional[List[str]] = None
    filters: Optional[List[Union[QueryFilter, QueryFilterGroup]]] = None
    relations: Optional[List['QueryRelation']] = None


class QueryDsl(BaseModel):
    model: str
    select: Optional[List[str]] = None
    filters: Optional[List[Union[QueryFilter, QueryFilterGroup]]] = None
    relations: Optional[List[QueryRelation]] = None
    orderBy: Optional[List[str]] = None
    limit: Optional[int] = Field(None, ge=1, le=1000)
    offset: Optional[int] = Field(None, ge=0)


# Rebuild recursive models in Pydantic v2
QueryFilterGroup.model_rebuild()
QueryRelation.model_rebuild()


