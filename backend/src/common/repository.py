from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional, List, Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete

T = TypeVar("T")

class IRepository(ABC, Generic[T]):
    """Abstract base repository interface required by ECC Repository Pattern."""
    @abstractmethod
    async def find_all(self, skip: int = 0, limit: int = 100, **filters: Any) -> List[T]:
        pass

    @abstractmethod
    async def find_by_id(self, entity_id: Any) -> Optional[T]:
        pass

    @abstractmethod
    async def create(self, data: Dict[str, Any]) -> T:
        pass

    @abstractmethod
    async def update(self, entity_id: Any, data: Dict[str, Any]) -> Optional[T]:
        pass

    @abstractmethod
    async def delete(self, entity_id: Any) -> bool:
        pass

class BaseSQLAlchemyRepository(IRepository[T]):
    """SQLAlchemy implementation of the Repository Pattern."""
    def __init__(self, session: AsyncSession, model_class: type[T]):
        self.session = session
        self.model_class = model_class

    async def find_all(self, skip: int = 0, limit: int = 100, **filters: Any) -> List[T]:
        query = select(self.model_class).offset(skip).limit(limit)
        for key, value in filters.items():
            if hasattr(self.model_class, key) and value is not None:
                query = query.where(getattr(self.model_class, key) == value)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def find_by_id(self, entity_id: Any) -> Optional[T]:
        return await self.session.get(self.model_class, entity_id)

    async def create(self, data: Dict[str, Any]) -> T:
        instance = self.model_class(**data)
        self.session.add(instance)
        await self.session.commit()
        await self.session.refresh(instance)
        return instance

    async def update(self, entity_id: Any, data: Dict[str, Any]) -> Optional[T]:
        instance = await self.find_by_id(entity_id)
        if not instance:
            return None
        for key, value in data.items():
            if hasattr(instance, key) and value is not None:
                setattr(instance, key, value)
        await self.session.commit()
        await self.session.refresh(instance)
        return instance

    async def delete(self, entity_id: Any) -> bool:
        instance = await self.find_by_id(entity_id)
        if not instance:
            return False
        await self.session.delete(instance)
        await self.session.commit()
        return True
