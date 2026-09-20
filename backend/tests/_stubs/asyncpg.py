class UniqueViolationError(Exception):
    pass


class Connection:
    pass


class Pool:
    pass


async def create_pool(*_args, **_kwargs):
    return Pool()
