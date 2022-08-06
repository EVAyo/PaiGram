from .models import Sign
from .repositories import SignRepository


class SignServices:
    def __init__(self, sign_repository: SignRepository) -> None:
        self._repository: SignRepository = sign_repository

    async def get_all(self):
        return await self._repository.get_all()

    async def add(self, sign: Sign):
        return await self._repository.add(sign)

    async def remove(self, sign: Sign):
        return await self._repository.remove(sign)

    async def update(self, sign: Sign):
        return await self._repository.update(sign)

    async def get_by_user_id(self, user_id: int):
        return await self._repository.get_by_user_id(user_id)